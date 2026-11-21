"""
标题子图：第一个真正的"标题 Agent"

把调研员（标题任务）与标题策划组装成一个完整子图：
    research_start(清空消息) -> react_model(PLAN) -> [条件边] -> react_tools(执行搜索)
                                          |-> done -> research_summary(SUMMARY -> title_research)
                                                      -> title_generate(GENERATE_TITLES_TASK -> titles)
                                                      -> title_score(SCORE_TITLES_TASK -> title_scores)
                                                      -> END

角色分工：
- 调研段：PLAN 给 react_model（模型自主决定是否调用 web_search），SUMMARY 给总结节点
- 生成段：GENERATE_TITLES_TASK 拼入 title_research，结构化输出 TitleList（3 个标题）
- 评分段：SCORE_TITLES_TASK 对 3 个标题评分（准确性/独特性/SEO），结构化输出 TitleScoreList
- 打回重跑：review_feedback 非空时，生成段任务指令追加 REVIEW_ADDON_FOR_TITLES

主图（supervisor）把本子图作为单个节点，质量门审完后：
- 通过/超限 -> 放行进入下一阶段
- 打回 -> 携带 review_feedback 重跑本子图
"""
from langgraph.graph import END, START, StateGraph

from src.blog_agent.agent.agents.researcher_prompts import (
    RESEARCH_SYSTEM,
    RESEARCH_TITLES_PLAN,
    RESEARCH_TITLES_SUMMARY,
)
from src.blog_agent.agent.agents.title_prompts import (
    GENERATE_TITLES_SYSTEM,
    GENERATE_TITLES_TASK,
    REVIEW_ADDON_FOR_TITLES,
    SCORE_TITLES_SYSTEM,
    SCORE_TITLES_TASK,
    TitleList,
    TitleScoreList,
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
from src.blog_agent.agent.agents.short_brief import short_brief, title_request
from src.blog_agent.agent.evidence import personal_reflection

# 标题调研阶段只绑定搜索工具（配图/格式化等工具不属于调研段）
RESEARCH_TOOLS = [web_search]


def build_title_graph():
    """构造标题子图（返回可被主图 add_node 的子图实例）"""
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
            task_builder=lambda s: (
                f"为短文选题《{s.get('topic', '')}》检索原始参考资料。优先定位能回答核心问题的官方文档或科学机构；"
                "用该来源语言和具体概念进行检索。无需分析相似标题或流量。"
                if short_brief(s) else RESEARCH_TITLES_PLAN.format(topic=s.get("topic", ""))),
            tools=RESEARCH_TOOLS,
            model_role="researcher",
            temperature=0.3,
        ),
    )
    builder.add_node("research_tools", make_react_tools_node(RESEARCH_TOOLS))

    # ---- 调研段：总结（基于真实搜索结果输出标题调研结论）----
    builder.add_node(
        "research_summary",
        make_output_node(
            RESEARCH_SYSTEM,
            task_builder=lambda s: (
                f"主题：{s.get('topic', '')}\n" + RESEARCH_TITLES_SUMMARY
                + "\n\n【本次联网检索到的真实资料】\n"
                + collect_search_results(s)
            ),
            output_key="title_research",
            model_role="researcher",
            temperature=0.3,
        ),
    )

    # ---- 生成段：标题策划（结构化输出 3 个标题）----
    builder.add_node(
        "title_generate",
        make_output_node(
            GENERATE_TITLES_SYSTEM,
            task_builder=lambda s: (
                (title_request(s) if short_brief(s) else GENERATE_TITLES_TASK.format(
                    topic=s.get("topic", ""),
                    title_research=s.get("title_research", ""),
                ))
                + "\n【原始检索记录，只有这些资料可支持事实断言】\n" + collect_search_results(s)
                + (
                    REVIEW_ADDON_FOR_TITLES.format(
                        review_feedback=s.get("review_feedback", ""),
                        previous_titles="\n".join(f"{i}. {title}" for i, title in enumerate(s.get("titles") or [], 1)),
                    )
                    if s.get("review_feedback")
                    else ""
                )
            ),
            output_key="titles",
            model_role="title",
            temperature=0.7,
            structured_schema=TitleList,
            extractor=lambda obj: obj.titles,
        ),
    )

    # ---- 生成段：标题评分（对刚生成的 3 个标题评分，供前端展示）----
    # 注意：评分是子图内固定格式产出（非主编把关），显式关思考保持快速；
    # 主编质量门（supervisor title_gate）才是 reviewer 开思考的评审环节
    builder.add_node(
        "title_score",
        make_output_node(
            SCORE_TITLES_SYSTEM,
            task_builder=lambda s: SCORE_TITLES_TASK.format(
                topic=s.get("topic", ""),
                title_research=s.get("title_research", ""),
                titles_text="\n".join(
                    f"{i + 1}. {t}" for i, t in enumerate(s.get("titles", []))
                ),
            ),
            output_key="title_scores",
            model_role="title",  # 固定 JSON 评分，用 plus 模型即可，比 reviewer(max) 快一半
            temperature=0.3,
            structured_schema=TitleScoreList,
            extractor=lambda obj: [sc.model_dump() for sc in obj.scores],
            enable_thinking=False,  # 子图内评分：固定格式，保持关思考提速
        ),
    )

    # ---- 边：入口路由（打回重跑时跳过调研，直接用已有 title_research 重新生成）----
    def _entry_router(state: AgentState) -> str:
        if (short_brief(state) and personal_reflection(state)) or (state.get("title_research") and state.get("review_count", 0) > 0):
            return "regenerate"  # 打回重跑：跳过调研
        return "research"        # 首次：正常调研

    builder.add_conditional_edges(
        START,
        _entry_router,
        {"research": "research_start", "regenerate": "title_generate"},
    )
    builder.add_edge("research_start", "research_plan")
    builder.add_conditional_edges(
        "research_plan",
        has_tool_calls,
        {"tools": "research_tools", "done": "research_summary"},
    )
    builder.add_edge("research_tools", "research_plan")
    builder.add_edge("research_summary", "title_generate")
    builder.add_edge("title_generate", "title_score")
    builder.add_edge("title_score", END)

    return builder.compile()


if __name__ == "__main__":
    # 本地冒烟：docker exec 内直接跑，验证标题链路（调研 + 生成）
    graph = build_title_graph()
    from src.blog_agent.clients.provider_budget import provider_run

    with provider_run():
        result = graph.invoke(
            {
                "topic": "2026年 AI Agent 发展趋势",
                "max_review_rounds": 2,
            }
        )
    print("=== title_research ===")
    print((result.get("title_research") or "")[:800])
    print("=== titles ===")
    for i, t in enumerate(result.get("titles", [])):
        print(f"{i + 1}. {t}")
