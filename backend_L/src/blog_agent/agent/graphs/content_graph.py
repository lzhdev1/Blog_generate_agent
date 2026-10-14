"""
正文子图：正文 Agent

把调研员（正文资料任务）与写手组装成一个完整子图：
    research_start(清空消息) -> react_model(PLAN/SUPPLEMENT) -> [条件边] -> react_tools(执行搜索)
                                          |-> done -> research_summary(SUMMARY -> content_research)
                                                      -> content_generate(GENERATE_CONTENT_TASK
                                                                          -> content + writing_thoughts)
                                                      -> END

本子图相比标题/大纲子图的特殊点：
1. 调研段支持【审稿打回后的补充/重新调研】：
   - research_suggestions 非空 -> PLAN 切换为 RESEARCH_CONTENT_SUPPLEMENT（只搜指定方向）
   - 总结节点按 research_type 决定：补充调研 -> 追加到旧 content_research；重新调研 -> 覆盖
2. 正文生成合并输出「写作思路 + 正文」，由节点拆分写入 content / writing_thoughts
   （思路展示在最终页面右侧栏，正文是最终产物）
3. 打回重跑：review_feedback 非空时拼入 REVIEW_SECTION
"""
from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from src.blog_agent.agent.agents.prompt_utils import level_desc, style_desc, word_count_requirement
from src.blog_agent.agent.agents.researcher_prompts import (
    RESEARCH_CONTENT_PLAN,
    RESEARCH_CONTENT_SUMMARY,
    RESEARCH_CONTENT_SUPPLEMENT,
    RESEARCH_SYSTEM,
)
from src.blog_agent.agent.agents.writer_prompts import (
    CONTENT_MARKER,
    GENERATE_CONTENT_SYSTEM,
    GENERATE_CONTENT_TASK,
    GENERATE_CONTENT_THOUGHTS_ADDON,
    REVIEW_SECTION,
    THOUGHTS_MARKER,
)
from src.blog_agent.agent.nodes.output_node import collect_search_results
from src.blog_agent.agent.nodes.react_model import make_react_model_node
from src.blog_agent.agent.nodes.react_tools import (
    has_tool_calls,
    make_react_tools_node,
)
from src.blog_agent.agent.state import AgentState
from src.blog_agent.agent.tools import web_search
from src.blog_agent.clients.llm_client import get_chat_model

RESEARCH_TOOLS = [web_search]


# ============================================================
# 正文调研总结节点（首次 / 补充 / 重新 三态）
# ============================================================

def make_content_research_summary_node():
    """正文调研总结节点：基于真实搜索结果输出调研结论。

    - 首次调研：RESEARCH_CONTENT_SUMMARY（完整调研清单 + 按章节资料 + 可靠性说明）
    - 补充调研（research_type=补充调研）：追加到旧 content_research 之后
    - 重新调研（research_type=重新调研）：覆盖旧 content_research
    """
    model = get_chat_model(role="researcher", temperature=0.3)

    def research_summary_node(state: AgentState) -> Dict[str, Any]:
        search_text = collect_search_results(state)

        # 审稿打回需要补充/重新调研
        if state.get("research_suggestions"):
            task = (
                RESEARCH_CONTENT_SUPPLEMENT.format(
                    extra_suggestions=state.get("research_suggestions", "")
                )
                + "\n\n【本次补充检索到的真实资料】\n"
                + search_text
            )
            new_research = str(model.invoke(task).content)
            review: Dict[str, Any] = state.get("review_result") or {}
            research_type = review.get("research_type", "补充调研")
            if research_type == "重新调研":
                return {"content_research": new_research}  # 覆盖
            old = state.get("content_research", "") or ""
            merged = (
                (old + "\n\n【补充调研】\n" + new_research)
                if old
                else new_research
            )
            return {"content_research": merged}  # 追加
        # 首次调研
        task = (
            RESEARCH_CONTENT_SUMMARY
            + "\n\n【本次联网检索到的真实资料】\n"
            + search_text
        )
        return {"content_research": str(model.invoke(task).content)}

    return research_summary_node


# ============================================================
# 正文生成节点（合并输出「思路 + 正文」，节点拆分写两个字段）
# ============================================================

def _find_markdown_start(text: str) -> int:
    """在文本中找第一个 markdown 章节标题（## 开头）的位置，跳过代码块内的行。

    用于兜底拆分：模型漏掉正文分隔标记时，正文通常以大纲第一个章节标题开头。
    """
    in_code = False
    for i, line in enumerate(text.splitlines(keepends=True)):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if not in_code and stripped.startswith("## "):
            offset = 0
            for prev in text.splitlines(keepends=True)[:i]:
                offset += len(prev)
            return offset
    return -1


def split_thoughts_and_content(text: str):
    """按分隔标记拆分「写作思路 + 正文」合并输出。

    - 两个标记都在：标准拆分
    - 只有思路标记：思路标记后第一个 markdown 章节标题之前为思路，之后为正文
    - 标记全缺失：整个输出视为正文（思路为空，正文优先不丢内容）
    """
    text = text.strip()
    if THOUGHTS_MARKER in text and CONTENT_MARKER in text:
        thoughts = text.split(THOUGHTS_MARKER, 1)[1].split(CONTENT_MARKER, 1)[0].strip()
        content = text.split(CONTENT_MARKER, 1)[1].strip()
        return thoughts, content
    if THOUGHTS_MARKER in text:
        after = text.split(THOUGHTS_MARKER, 1)[1].strip()
        start = _find_markdown_start(after)
        if start > 0:
            thoughts = after[:start].strip()
            content = after[start:].strip()
            return thoughts, content
        return after, ""  # 思路标记后没有正文章节标题，整体视为思路
    return "", text


def make_content_generate_node():
    """正文生成节点：首次写作合并输出思路+正文；打回重跑只输出正文（带审稿意见）"""
    model = get_chat_model(role="writer", temperature=0.7)

    def content_generate_node(state: AgentState) -> Dict[str, Any]:
        review_feedback = state.get("review_feedback", "") or ""
        review_section = (
            REVIEW_SECTION.format(review_feedback=review_feedback)
            if review_feedback
            else ""
        )
        task = GENERATE_CONTENT_TASK.format(
            selected_title=state.get("selected_title", ""),
            content_research=state.get("content_research", ""),
            word_count_requirement=word_count_requirement(state.get("word_count")),
            level_requirement=level_desc(state.get("level")) or "无特殊要求",
            extra_requirements=state.get("content_extra_requirements", "") or "无",
            outline=state.get("outline", ""),
            review_section=review_section,
        )
        # 首次写作：合并输出「写作思路 + 正文」；打回重跑时只输出正文
        if not review_feedback:
            task += "\n" + GENERATE_CONTENT_THOUGHTS_ADDON.format(
                thoughts_marker=THOUGHTS_MARKER,
                content_marker=CONTENT_MARKER,
            )

        resp = str(model.invoke(task).content)
        thoughts, content = split_thoughts_and_content(resp)
        return {"content": content, "writing_thoughts": thoughts}

    return content_generate_node


# ============================================================
# 子图组装
# ============================================================

def build_content_graph():
    """构造正文子图（返回可被主图 add_node 的子图实例）"""
    builder = StateGraph(AgentState)

    # ---- 调研段：ReAct 循环（审稿打回时切换为补充/重新调研指令）----
    builder.add_node(
        "research_start",
        lambda state: {"messages": []},  # 空列表 = 清空信号，重置本子图 ReAct 历史
    )
    builder.add_node(
        "research_plan",
        make_react_model_node(
            RESEARCH_SYSTEM,
            task_builder=lambda s: (
                RESEARCH_CONTENT_SUPPLEMENT.format(
                    extra_suggestions=s.get("research_suggestions", "")
                )
                if s.get("research_suggestions")
                else RESEARCH_CONTENT_PLAN.format(
                    selected_title=s.get("selected_title", ""),
                    outline=s.get("outline", ""),
                )
            ),
            tools=RESEARCH_TOOLS,
            model_role="researcher",
            temperature=0.3,
        ),
    )
    builder.add_node("research_tools", make_react_tools_node(RESEARCH_TOOLS))
    builder.add_node("research_summary", make_content_research_summary_node())

    # ---- 生成段：写手 ----
    builder.add_node("content_generate", make_content_generate_node())

    # ---- 边 ----
    builder.add_edge(START, "research_start")
    builder.add_edge("research_start", "research_plan")
    builder.add_conditional_edges(
        "research_plan",
        has_tool_calls,
        {"tools": "research_tools", "done": "research_summary"},
    )
    builder.add_edge("research_tools", "research_plan")
    builder.add_edge("research_summary", "content_generate")
    builder.add_edge("content_generate", END)

    return builder.compile()


if __name__ == "__main__":
    # 本地冒烟：docker exec 内直接跑，验证正文链路（调研 + 写作）
    graph = build_content_graph()
    result = graph.invoke(
        {
            "topic": "2026年 AI Agent 发展趋势",
            "selected_title": "Agent企业落地账本：按效果计费与垂直场景ROI测算",
            "article_style": "technical",
            "need_image": True,
            "word_count": 1200,
            "level": "advanced",
            "content_extra_requirements": "突出落地成本和ROI对比",
            "outline": (
                "## 为什么企业开始为Agent买单\n"
                "说明企业采用Agent的驱动力和成本痛点。\n"
                "## 按效果计费的商业模式\n"
                "介绍按效果计费模式及其适用场景。\n"
                "## 垂直场景ROI测算方法\n"
                "给出ROI测算的框架与案例。\n"
                "## 总结与展望\n"
                "总结要点并展望趋势。"
            ),
            "max_review_rounds": 2,
        }
    )
    print("=== content_research ===")
    print((result.get("content_research") or "")[:600])
    print("=== writing_thoughts ===")
    print((result.get("writing_thoughts") or "")[:400])
    print("=== content ===")
    print((result.get("content") or "")[:1500])
