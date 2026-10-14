"""
主图（Supervisor）：一主多从编排

主 Agent 负责把控每一个子 Agent 的质量：子 Agent 产出 -> 主 Agent 质量门评审
-> 通过放行（切换下一阶段）/ 打回重跑（最多 max_review_rounds 次）/ 超限强制放行。

流程（标题 -> 大纲 -> 正文 三阶段）：
    START -> title_agent -> title_gate
                |pass/force_pass -> to_outline -> outline_agent -> outline_gate
                |retry -> apply_title_feedback -> title_agent
                    |pass/force_pass -> to_content -> content_agent -> content_gate
                    |retry -> apply_outline_feedback -> outline_agent
                        |pass/force_pass -> to_done -> END
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
from src.blog_agent.agent.agents.prompt_utils import style_desc
from src.blog_agent.agent.agents.reviewer_prompts import (
    REVIEW_CONTENT_SYSTEM,
    REVIEW_CONTENT_TASK,
)
from src.blog_agent.agent.agents.title_prompts import (
    REVIEW_TITLES_SYSTEM,
    REVIEW_TITLES_TASK,
)
from src.blog_agent.agent.graphs.content_graph import build_content_graph
from src.blog_agent.agent.graphs.outline_graph import build_outline_graph
from src.blog_agent.agent.graphs.title_graph import build_title_graph
from src.blog_agent.agent.nodes.quality_gate import (
    OutlineReviewResult,
    ReviewResult,
    TitleReviewResult,
    count_chars,
    count_image_marks,
    make_apply_feedback_node,
    make_quality_gate_node,
    review_router,
)
from src.blog_agent.agent.state import AgentState


# ============================================================
# 各阶段质量门的任务拼装
# ============================================================

def _build_title_review_task(state) -> str:
    titles = state.get("titles") or []
    titles_text = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return REVIEW_TITLES_TASK.format(
        topic=state.get("topic", ""),
        title_research=state.get("title_research", ""),
        titles_text=titles_text,
    )


def _build_outline_review_task(state) -> str:
    image_requirement = "需要配图（大纲中应有具体的配图注释，禁止占位文字）" if state.get("need_image") else "不需要配图"
    return REVIEW_OUTLINE_TASK.format(
        selected_title=state.get("selected_title", ""),
        style_desc=style_desc(state),
        outline_research=state.get("outline_research", ""),
        image_requirement=image_requirement,
        extra_requirements=state.get("extra_requirements", "") or "无",
        outline=state.get("outline", ""),
    )


def _build_content_review_task(state) -> str:
    content = state.get("content", "") or ""
    outline = state.get("outline", "") or ""
    # 硬性约束的代码级预计算（标题一致性/字数/配图数量）
    required_images = count_image_marks(outline) if state.get("need_image") else 0
    actual_images = count_image_marks(content)
    return REVIEW_CONTENT_TASK.format(
        selected_title=state.get("selected_title", ""),
        style_desc=style_desc(state),
        word_count=state.get("word_count") or 800,
        actual_word_count=count_chars(content),
        required_image_count=required_images,
        actual_image_count=actual_images,
        outline=outline,
        content_research=state.get("content_research", ""),
        content=content,
    )


# ============================================================
# 阶段切换节点：清空评审状态，避免跨阶段累积
# ============================================================

def make_stage_switch(stage: str):
    """生成阶段切换节点：设置 stage 并清空上一阶段的评审相关状态"""

    def stage_switch_node(state: AgentState) -> Dict[str, Any]:
        return {
            "stage": stage,
            "review_count": 0,
            "review_result": None,
            "review_feedback": "",
            "research_suggestions": "",
        }

    return stage_switch_node


# ============================================================
# 主图组装
# ============================================================

def build_supervisor_graph(max_review_rounds: int = 3):
    """构造主图：标题 -> 大纲 -> 正文 全链路（子图 + 质量门 + 打回循环）"""
    builder = StateGraph(AgentState)

    # ---- 子 Agent（子图作为单个节点）----
    builder.add_node("title_agent", build_title_graph())
    builder.add_node("outline_agent", build_outline_graph())
    builder.add_node("content_agent", build_content_graph())

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
    builder.add_node("to_done", make_stage_switch("done"))

    # ---- 标题阶段 ----
    builder.add_edge(START, "title_agent")
    builder.add_edge("title_agent", "title_gate")
    builder.add_conditional_edges(
        "title_gate",
        review_router,
        {
            "pass": "to_outline",
            "retry": "apply_title_feedback",
            "force_pass": "to_outline",
        },
    )
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
            "force_pass": "to_content",
        },
    )
    builder.add_edge("apply_outline_feedback", "outline_agent")

    # ---- 正文阶段 ----
    builder.add_edge("to_content", "content_agent")
    builder.add_edge("content_agent", "content_gate")
    builder.add_conditional_edges(
        "content_gate",
        review_router,
        {
            "pass": "to_done",
            "retry": "apply_content_feedback",
            "force_pass": "to_done",
        },
    )
    builder.add_edge("apply_content_feedback", "content_agent")
    builder.add_edge("to_done", END)

    return builder.compile()


if __name__ == "__main__":
    # 本地冒烟：docker exec 内直接跑，验证全链路（标题 -> 大纲 -> 正文 + 三道质量门）
    graph = build_supervisor_graph(max_review_rounds=2)
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
        f"traffic={review.get('traffic_forecast')} review_count={result.get('review_count')}"
    )
