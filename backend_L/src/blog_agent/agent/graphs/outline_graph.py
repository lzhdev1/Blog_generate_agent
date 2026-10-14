"""
大纲子图：大纲 Agent

把调研员（大纲任务）与大纲师组装成一个完整子图：
    research_start(清空消息) -> react_model(PLAN) -> [条件边] -> react_tools(执行搜索)
                                          |-> done -> research_summary(SUMMARY -> outline_research)
                                                      -> outline_generate(GENERATE_OUTLINE_TASK -> outline)
                                                      -> END

角色分工：
- 调研段：PLAN 给 react_model（模型分析已选标题+风格后自主搜索同类文章结构），
  SUMMARY 给总结节点（产出 outline_research：结构类型分析 + 大纲制定建议）
- 生成段：GENERATE_OUTLINE_TASK 拼入 selected_title/style_desc/outline_research/
  配图要求/额外要求，文本输出 markdown 大纲（含配图注释）
- 打回重跑：review_feedback 非空时，生成段任务指令追加 REVIEW_ADDON_FOR_OUTLINE
"""
from langgraph.graph import END, START, StateGraph

from src.blog_agent.agent.agents.outliner_prompts import (
    GENERATE_OUTLINE_SYSTEM,
    GENERATE_OUTLINE_TASK,
    IMAGE_MARKER_NONE,
    IMAGE_MARKER_REQUIREMENT,
    REVIEW_ADDON_FOR_OUTLINE,
)
from src.blog_agent.agent.agents.prompt_utils import style_desc
from src.blog_agent.agent.agents.researcher_prompts import (
    RESEARCH_OUTLINE_PLAN,
    RESEARCH_OUTLINE_SUMMARY,
    RESEARCH_SYSTEM,
)
from src.blog_agent.agent.nodes.output_node import (
    collect_search_results,
    make_output_node,
)
from src.blog_agent.agent.nodes.react_model import make_react_model_node
from src.blog_agent.agent.nodes.react_tools import (
    has_tool_calls,
    make_react_tools_node,
)
from src.blog_agent.agent.state import AgentState
from src.blog_agent.agent.tools import web_search

RESEARCH_TOOLS = [web_search]


def build_outline_graph():
    """构造大纲子图（返回可被主图 add_node 的子图实例）"""
    builder = StateGraph(AgentState)

    # ---- 调研段：ReAct 循环 ----
    builder.add_node(
        "research_start",
        lambda state: {"messages": []},  # 空列表 = 清空信号，重置本子图 ReAct 历史
    )
    builder.add_node(
        "research_plan",
        make_react_model_node(
            RESEARCH_SYSTEM,
            task_builder=lambda s: RESEARCH_OUTLINE_PLAN.format(
                selected_title=s.get("selected_title", ""),
                style_desc=style_desc(s),
                topic=s.get("topic", ""),
            ),
            tools=RESEARCH_TOOLS,
            model_role="researcher",
            temperature=0.3,
        ),
    )
    builder.add_node("research_tools", make_react_tools_node(RESEARCH_TOOLS))

    # ---- 调研段：总结（基于真实搜索结果输出大纲调研结论）----
    builder.add_node(
        "research_summary",
        make_output_node(
            RESEARCH_SYSTEM,
            task_builder=lambda s: (
                RESEARCH_OUTLINE_SUMMARY
                + "\n\n【本次联网检索到的真实资料】\n"
                + collect_search_results(s)
            ),
            output_key="outline_research",
            model_role="researcher",
            temperature=0.3,
        ),
    )

    # ---- 生成段：大纲师（文本输出 markdown 大纲）----
    builder.add_node(
        "outline_generate",
        make_output_node(
            GENERATE_OUTLINE_SYSTEM,
            task_builder=lambda s: (
                GENERATE_OUTLINE_TASK.format(
                    selected_title=s.get("selected_title", ""),
                    style_desc=style_desc(s),
                    outline_research=s.get("outline_research", ""),
                    image_requirement=(
                        IMAGE_MARKER_REQUIREMENT if s.get("need_image") else IMAGE_MARKER_NONE
                    ),
                    extra_requirements=s.get("extra_requirements", "") or "无",
                )
                + (
                    REVIEW_ADDON_FOR_OUTLINE.format(
                        review_feedback=s.get("review_feedback", "")
                    )
                    if s.get("review_feedback")
                    else ""
                )
            ),
            output_key="outline",
            model_role="outliner",
            temperature=0.6,
        ),
    )

    # ---- 边：调研段循环 + 汇入生成段 ----
    builder.add_edge(START, "research_start")
    builder.add_edge("research_start", "research_plan")
    builder.add_conditional_edges(
        "research_plan",
        has_tool_calls,
        {"tools": "research_tools", "done": "research_summary"},
    )
    builder.add_edge("research_tools", "research_plan")
    builder.add_edge("research_summary", "outline_generate")
    builder.add_edge("outline_generate", END)

    return builder.compile()


if __name__ == "__main__":
    # 本地冒烟：docker exec 内直接跑，验证大纲链路（调研 + 生成）
    graph = build_outline_graph()
    result = graph.invoke(
        {
            "topic": "2026年 AI Agent 发展趋势",
            "selected_title": "Agent企业落地账本：按效果计费与垂直场景ROI测算",
            "article_style": "technical",
            "need_image": True,
            "extra_requirements": "突出落地成本和ROI对比",
            "max_review_rounds": 2,
        }
    )
    print("=== outline_research ===")
    print((result.get("outline_research") or "")[:600])
    print("=== outline ===")
    print((result.get("outline") or "")[:1500])
