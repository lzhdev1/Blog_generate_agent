"""
主图（Supervisor）：一主多从编排

主 Agent 负责把控每一个子 Agent 的质量：子 Agent 产出 -> 主 Agent 质量门评审
-> 通过放行（切换下一阶段）/ 打回重跑（最多 max_review_rounds 次）/ 超限停止并保留意见。

流程（标题 -> 大纲 -> 正文 三阶段）：
    START -> title_agent -> title_gate
                |pass -> to_outline -> outline_agent -> outline_gate
                |retry -> apply_title_feedback -> title_agent
                    |pass -> to_content -> content_agent -> content_gate
                    |retry -> apply_outline_feedback -> outline_agent
                        |pass -> to_done -> END
                        |retry -> apply_content_feedback -> content_agent

要点：
1. 阶段切换节点（to_outline / to_content / to_done）：清空评审相关状态
   （review_count/review_result/review_feedback/research_suggestions），避免跨阶段累积
2. 打回重跑：apply_xxx_feedback 记录打回次数并写审稿意见/调研建议，
   子图重跑时携带（正文阶段还会触发补充/重新调研）
3. 质量门机制（make_quality_gate_node / review_router / apply_feedback）是所有 Agent
   共用的模板：传入不同的评审 prompt 与结果 schema 即得到对应阶段的质量门
"""
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.blog_agent.agent.agents.outliner_prompts import (
    REVIEW_OUTLINE_SYSTEM,
    REVIEW_OUTLINE_TASK,
)
from src.blog_agent.agent.agents.prompt_utils import level_desc, style_desc, word_count_bounds
from src.blog_agent.agent.agents.reviewer_prompts import (
    REVIEW_CONTENT_SYSTEM,
    REVIEW_CONTENT_TASK,
)
from src.blog_agent.agent.agents.title_prompts import (
    REVIEW_TITLES_SYSTEM,
    REVIEW_TITLES_TASK,
)
from config.settings import settings
from src.blog_agent.agent.graphs.content_graph import build_content_graph
from src.blog_agent.agent.evidence import evidence_prompt
from src.blog_agent.agent.graphs.outline_graph import build_outline_graph
from src.blog_agent.agent.graphs.title_graph import build_title_graph
from src.blog_agent.agent.nodes.quality_gate import (
    OutlineReviewResult,
    ReviewResult,
    TitleReviewResult,
    count_chars,
    count_image_marks,
    grade_research_usage,
    make_apply_feedback_node,
    make_quality_gate_node,
    minimum_body_score,
    choose_ranked_title,
    review_one_title,
    review_router,
)
from src.blog_agent.agent.state import AgentState
from src.blog_agent.agent.nodes.output_node import collect_search_results
from src.blog_agent.agent.nodes.body_length import rewrite_to_word_range
from src.blog_agent.agent.agents.short_brief import short_brief


# ============================================================
# 各阶段质量门的任务拼装
# ============================================================

def _build_title_review_task(state) -> str:
    titles = state.get("titles") or []
    titles_text = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    if short_brief(state):
        return (f"请把下列三个标题分别和作者选题《{state.get('topic', '')}》核对：\n{titles_text}\n"
                "给出相关度、体裁匹配度和吸引力。表达清楚具体即有读者价值；无需制造悬念、使用营销语或引入额外科学结论。"
                "若标题存在超出题意的预设，具体指出对应的那个标题和原话。"
                "\n可参考的检索结果：\n" + collect_search_results(state))
    return REVIEW_TITLES_TASK.format(
        topic=state.get("topic", ""),
        title_research=state.get("title_research", ""),
        titles_text=titles_text,
    ) + "\n【原始检索记录】\n" + collect_search_results(state)


def _build_outline_review_task(state) -> str:
    if short_brief(state):
        return (f"审阅短稿的章节计划。《{state.get('selected_title', '')}》的实际大纲如下：\n"
                f"{state.get('outline', '')}\n逐项查看章节合起来能否回答作者的原始选题。"
                "本次委托的大纲是章节名清单。能由标题看出各节任务即可，没有章下说明、同类文章调研、"
                "三级标题或独立总结均不构成缺项。技术操作应有实作位置，科普应能分别解释题中的现象。"
                "不相关的额外知识不能弥补漏题；无依据的结论不应预埋在标题中。")
    image_requirement = "需要配图（大纲中应有具体的配图注释，禁止占位文字）" if state.get("need_image") else "不需要配图"
    return REVIEW_OUTLINE_TASK.format(
        selected_title=state.get("selected_title", ""),
        style_desc=style_desc(state),
        outline_research=state.get("outline_research", ""),
        image_requirement=image_requirement,
        extra_requirements=state.get("extra_requirements", "") or "无",
        outline=state.get("outline", ""),
    ) + "\n【原始检索记录】\n" + collect_search_results(state)


def _build_content_review_task(state) -> str:
    content = state.get("content", "") or ""
    outline = state.get("outline", "") or ""
    # 硬性约束的代码级预计算（标题一致性/字数/配图数量）
    required_images = count_image_marks(outline) if state.get("need_image") else 0
    actual_images = count_image_marks(content)
    target_words = state.get("word_count") or 800
    min_word_count, max_word_count = word_count_bounds(target_words)
    edited = state.get("editor_revision")
    return REVIEW_CONTENT_TASK.format(
        selected_title=state.get("selected_title", ""),
        style_desc=style_desc(state),
        word_count=target_words,
        level=level_desc(state.get("level")) or "无特殊要求",
        extra_requirements=state.get("content_extra_requirements") or "无",
        min_word_count=min_word_count,
        max_word_count=max_word_count,
        actual_word_count=count_chars(content),
        required_image_count=0 if edited else required_images,
        actual_image_count=0 if edited else actual_images,
        minimum_score=minimum_body_score(state),
        source_standard=("核对具体论断与原始来源，资料支持度至少为70分。" if grade_research_usage(state)
                         else "按文体核对叙述。没有外部事实主张时无需引用资料，该分项不设最低分。"),
        outline=outline,
        content_research=state.get("content_research", ""),
        content=content,
    ) + ("\n本次为作者编辑的排版稿，插图已处理，无须重建配图标记。" if edited else "") + evidence_prompt(state, index_sentences=True)


# ============================================================
# 阶段切换节点：清空评审状态，避免跨阶段累积
# ============================================================

def make_stage_switch(stage: str):
    """生成阶段切换节点：设置 stage 并清空上一阶段的评审相关状态"""

    def stage_switch_node(state: AgentState) -> Dict[str, Any]:
        updates = {
            "stage": stage,
            "review_count": 0,
            "review_result": None,
            "review_feedback": "",
            "research_suggestions": "",
        }
        if stage == "outline" and not state.get("selected_title"):
            updates["selected_title"] = choose_ranked_title(state)
        return updates

    return stage_switch_node


# ============================================================
# 主图组装
# ============================================================

def build_supervisor_graph(max_review_rounds: int = 3):
    """构造主图：标题 -> 大纲 -> 正文 全链路（子图 + 质量门 + 打回循环）"""
    builder = StateGraph(AgentState)
    builder.add_node("begin", lambda s: {
        "stage": "title",
        "max_review_rounds": s.get("max_review_rounds", max_review_rounds),
    })
    builder.add_node("rejected", lambda s: {"stage": "failed", "error": f"{s.get('stage')} 审核未通过"})
    builder.add_node("review_one_title", review_one_title)

    # ---- 子 Agent（子图作为单个节点）----
    builder.add_node("title_agent", build_title_graph())
    builder.add_node("outline_agent", build_outline_graph())
    builder.add_node("content_agent", build_content_graph())
    def fit_body_length(state):
        _, changed = rewrite_to_word_range(state)
        return {"content": state["content"]} if changed else {}

    builder.add_node("fit_body_length", fit_body_length)

    # ---- 质量门（主 Agent 评审）----
    builder.add_node(
        "title_gate",
        make_quality_gate_node(
            review_system=REVIEW_TITLES_SYSTEM,
            task_builder=_build_title_review_task,
            result_schema=TitleReviewResult,
            model_role="reviewer",
            enable_thinking=False,  # 标题审核：结构化判断，关思考提速
        ),
    )
    builder.add_node(
        "outline_gate",
        make_quality_gate_node(
            review_system=REVIEW_OUTLINE_SYSTEM,
            task_builder=_build_outline_review_task,
            result_schema=OutlineReviewResult,
            model_role="reviewer",
        ),
    )
    builder.add_node(
        "content_gate",
        make_quality_gate_node(
            review_system=REVIEW_CONTENT_SYSTEM,
            task_builder=_build_content_review_task,
            result_schema=ReviewResult,
            model_role="reviewer",
        ),
    )

    # ---- 打回反馈（每个阶段独立实例，回到对应子图）----
    builder.add_node("apply_title_feedback", make_apply_feedback_node())
    builder.add_node("apply_outline_feedback", make_apply_feedback_node())
    builder.add_node("apply_content_feedback", make_apply_feedback_node())

    # ---- 阶段切换（清评审状态）----
    builder.add_node("to_outline", make_stage_switch("outline"))
    builder.add_node("to_content", make_stage_switch("content"))
    builder.add_node("to_done", lambda s: {"stage": "done"})

    # ---- 标题阶段 ----
    builder.add_edge(START, "begin")
    builder.add_edge("begin", "title_agent")
    def title_review_route(state):
        if (short_brief(state) and len(state.get("titles") or []) == 3 and not state.get("selected_title")
                and (settings.enable_review or state.get("force_review"))):
            return "review_one_title"
        return "title_gate"

    builder.add_conditional_edges("title_agent", title_review_route, ["review_one_title", "title_gate"])
    builder.add_conditional_edges(
        "title_gate",
        review_router,
        {
            "pass": "to_outline",
            "retry": "review_one_title",
            "rejected": "review_one_title",
        },
    )
    builder.add_conditional_edges("review_one_title", review_router,
                                  {"pass": "to_outline", "retry": "apply_title_feedback", "rejected": "rejected"})
    builder.add_edge("apply_title_feedback", "title_agent")

    # ---- 大纲阶段 ----
    builder.add_edge("to_outline", "outline_agent")
    builder.add_edge("outline_agent", "outline_gate")
    builder.add_conditional_edges(
        "outline_gate",
        review_router,
        {
            "pass": "to_content",
            "retry": "apply_outline_feedback",
            "rejected": "rejected",
        },
    )
    builder.add_edge("apply_outline_feedback", "outline_agent")

    # ---- 正文阶段 ----
    builder.add_edge("to_content", "content_agent")
    builder.add_edge("content_agent", "fit_body_length")
    builder.add_edge("fit_body_length", "content_gate")
    builder.add_conditional_edges(
        "content_gate",
        review_router,
        {
            "pass": "to_done",
            "retry": "apply_content_feedback",
            "rejected": "rejected",
        },
    )
    builder.add_edge("apply_content_feedback", "content_agent")
    builder.add_edge("to_done", END)
    builder.add_edge("rejected", END)

    return builder.compile()


if __name__ == "__main__":
    # 本地冒烟：docker exec 内直接跑，验证全链路（标题 -> 大纲 -> 正文 + 三道质量门）
    graph = build_supervisor_graph(max_review_rounds=2)
    from src.blog_agent.clients.provider_budget import provider_run

    with provider_run():
        result = graph.invoke(
            {
                "topic": "2026年 AI Agent 发展趋势",
                "article_style": "technical",
                "need_image": True,
                "extra_requirements": "突出落地成本和ROI对比",
                "word_count": 1200,
                "level": "advanced",
                "content_extra_requirements": "突出落地成本和ROI对比",
                "selected_title": "Agent企业落地账本：按效果计费与垂直场景ROI测算",
                "max_review_rounds": 2,
            }
        )
    print("=== stage ===")
    print(result.get("stage"))
    print("=== titles ===")
    for i, t in enumerate(result.get("titles", [])):
        print(f"{i + 1}. {t}")
    print("=== outline (head) ===")
    print((result.get("outline") or "")[:800])
    print("=== content (head) ===")
    print((result.get("content") or "")[:800])
    print("=== review ===")
    review = result.get("review_result") or {}
    print(
        f"passed={review.get('passed')} score={review.get('score')} "
        f"review_count={result.get('review_count')}"
    )
