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
import re

from langgraph.graph import END, START, StateGraph

from src.blog_agent.agent.agents.prompt_utils import (
    editorial_brief,
    level_desc,
    style_desc,
    word_count_bounds,
    word_count_requirement,
)
from src.blog_agent.agent.agents.personal_note import write_personal_note
from src.blog_agent.agent.agents.source_questions import EVIDENCE_EXTRACTION_VERSION, refresh_saved_questions, research_questions
from src.blog_agent.agent.agents.short_tutorial import short_python_walkthrough, write_short_tutorial
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
from src.blog_agent.agent.evidence import evidence_prompt, personal_reflection, render_sources, requires_sources, source_records
from src.blog_agent.agent.nodes.react_model import make_react_model_node
from src.blog_agent.agent.nodes.react_tools import (
    has_tool_calls,
    make_react_tools_node,
)
from src.blog_agent.agent.state import AgentState
from src.blog_agent.agent.tools import web_search
from src.blog_agent.agent.agents.short_brief import short_brief
from src.blog_agent.agent.agents.science_brief import write_science_brief
from src.blog_agent.agent.tools.source_page import read_web_sources, select_pages
from src.blog_agent.clients.llm_client import get_chat_model

RESEARCH_TOOLS = [web_search, read_web_sources]


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
        review = state.get("review_result") or {}
        previous = (state.get("evidence_sources") or []) if state.get("research_suggestions") else []
        if review.get("research_type") == "重新调研":
            previous = []
        ids = dict(state.get("evidence_source_ids") or {})
        messages = state.get("messages") or []
        # Unstamped records represent saved pre-upgrade sources. New search snippets are discovery only.
        verified = []
        candidates = {}
        keywords = []
        requested_urls = []
        executed = {m.get("tool_call_id") for m in messages if m.get("role") == "tool" and m.get("search_result")}
        for message in messages:
            for call in message.get("tool_calls") or []:
                args = call.get("args") or {}
                keywords.append(str(args.get("keywords") or args.get("query") or ""))
                if call.get("name") == "read_web_sources" and call.get("id") not in executed:
                    requested_urls.extend(args.get("urls") or [])
            if message.get("role") != "tool":
                continue
            result = message.get("search_result") or {}
            direct = []
            for row in result.get("sources") or []:
                if row.get("origin") == "discovery":
                    candidates.setdefault(row["url"], row)
                else:
                    direct.append(row)
            if direct:
                verified.append({"role": "tool", "search_result": {"status": "ok", "sources": direct}})
        if not verified and (candidates or requested_urls):
            urls = select_pages(candidates, requested_urls, keywords)
            result = read_web_sources.invoke({"urls": urls, "keywords": " ".join(keywords) or state.get("topic", "")})
            verified.append({"role": "tool", "search_result": result})
        sources = source_records(verified, previous, ids, state.get("content") or "")
        if short_brief(state) and requires_sources(state) and (sources or candidates):
            # Keep one synthesis call. Its output drives separate, verifiable page reads for each question.
            more, trace = research_questions(model, state, sources, candidates)
            sources = source_records([*verified, *more], previous, ids, state.get("content") or "")
            ids.update({s["url"]: s["id"] for s in sources})
            summary = "\n".join(q["question"] + " → " + (
                ids.get(q["url"], "未取得资料") if q["status"] != "unavailable" else "未取得资料") for q in trace)
            return {"content_research": summary, "evidence_sources": sources,
                    "evidence_source_ids": ids, "evidence_questions": trace,
                    "evidence_extraction_version": EVIDENCE_EXTRACTION_VERSION}
        ids.update({s["url"]: s["id"] for s in sources})
        evidence = {"evidence_sources": sources, "evidence_source_ids": ids}
        search_text = render_sources(sources)

        # 审稿打回需要补充/重新调研
        if state.get("research_suggestions"):
            task = (
                RESEARCH_CONTENT_SUPPLEMENT.format(
                    extra_suggestions=state.get("research_suggestions", "")
                )
                + "\n\n【本次补充检索到的真实资料】\n"
                + search_text
            )
            new_research = str(model.invoke([("system", RESEARCH_SYSTEM), ("human", task)]).content)
            research_type = review.get("research_type", "补充调研")
            if research_type == "重新调研":
                return {"content_research": new_research, **evidence}
            old = state.get("content_research", "") or ""
            merged = (
                (old + "\n\n【补充调研】\n" + new_research)
                if old
                else new_research
            )
            return {"content_research": merged, **evidence}
        # 首次调研
        task = (
            f"文章标题：{state.get('selected_title', '')}\n大纲：{state.get('outline', '')}\n"
            + RESEARCH_CONTENT_SUMMARY
            + "\n\n【本次联网检索到的真实资料】\n"
            + search_text
        )
        return {"content_research": str(model.invoke([("system", RESEARCH_SYSTEM), ("human", task)]).content),
                **evidence}

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
        if not in_code and stripped.startswith(("# ", "## ")):
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
        if start >= 0:
            thoughts = after[:start].strip()
            content = after[start:].strip()
            return thoughts, content
        return after, ""  # 思路标记后没有正文章节标题，整体视为思路
    if CONTENT_MARKER in text:
        return "", text.split(CONTENT_MARKER, 1)[1].strip()
    return "", text


def make_content_generate_node():
    """正文生成节点：首次写作合并输出思路+正文；打回重跑只输出正文（带审稿意见）"""
    model = get_chat_model(role="writer", temperature=0.7)

    def content_generate_node(state: AgentState) -> Dict[str, Any]:
        refreshed = {}
        if personal_reflection(state):
            return write_personal_note(state)
        if short_brief(state) and state.get("article_style") == "popular_science" and state.get("evidence_questions"):
            refreshed = refresh_saved_questions(state)
            state = {**state, **refreshed}
            article = write_science_brief(state)
            if article:
                return {**refreshed, **article}
        if short_python_walkthrough(state):
            return write_short_tutorial(state)
        review_feedback = state.get("review_feedback", "") or ""
        review_section = (
            REVIEW_SECTION.format(review_feedback=review_feedback, previous_content=state.get("content") or "")
            if review_feedback
            else ""
        )
        outline_text = state.get("outline", "") or ""
        target_words = state.get("word_count") or 800
        lower_words, upper_words = word_count_bounds(target_words)
        h2_count = len(re.findall(r"^##\s", outline_text, re.M))
        h3_count = len(re.findall(r"^###\s", outline_text, re.M))
        heading_count = h2_count + h3_count or 1
        total_weight = 1.5 * h2_count + h3_count
        if total_weight:
            per_unit = target_words / total_weight
            per_h2_words = max(40, int(per_unit * 1.5))
            per_h3_words = max(30, int(per_unit))
        else:
            per_h2_words = per_h3_words = max(30, target_words // heading_count)
        word_budget_plan = (
            f"【字数预算分配（必须严格执行）】\n"
            f"全文目标 {target_words} 字（允许 {lower_words}-{upper_words} 字），"
            f"大纲共 {heading_count} 个标题（## {h2_count} 个，### {h3_count} 个）。\n"
            f"每个 ## 标题（含标题文字与正文）不得超过 {per_h2_words} 字；"
            f"每个 ### 标题（含标题文字与正文）不得超过 {per_h3_words} 字。\n"
            f"每个章节聚焦一个核心观点，按文风选用可核验的数据、案例或场景。\n"
            f"写作时按标题顺序累计字数：累计接近 {upper_words} 字时立即收束，不得继续扩写。\n"
            f"宁可压缩次要案例和背景铺垫，也不得超出 {upper_words} 字。"
        )
        task = GENERATE_CONTENT_TASK.format(
            selected_title=state.get("selected_title", ""),
            style=style_desc(state) or "根据选题和目标读者确定",
            content_research=state.get("content_research", ""),
            word_count_requirement=word_count_requirement(state.get("word_count")),
            word_budget_plan=word_budget_plan,
            per_h2_words=per_h2_words,
            per_h3_words=per_h3_words,
            level_requirement=level_desc(state.get("level")) or "无特殊要求",
            extra_requirements=state.get("content_extra_requirements", "") or "无",
            outline=outline_text,
            review_section=review_section,
        )
        if short_brief(state) and state.get("article_style") == "popular_science":
            task = (f"为原始选题《{state.get('topic', '')}》完成一篇中文科普。先区分题中每个问题，"
                    "逐个解释它的原因，再说明它们的关系。让读者能从来源原文推出每项结论。"
                    "若测量值、年代、出现频率或边缘细节没有直接依据，就省去，集中讲清核心现象。"
                    f"已定标题如下：\n# {state.get('selected_title', '')}\n以下是依序保留的章节：\n{outline_text}\n"
                    f"全篇目标 {target_words} 字（{lower_words}–{upper_words} 个非空白可见字符）。"
                    "关键论断就近标注真实来源编号。直接交付 Markdown 正文。")
        if short_brief(state) and state.get("article_style") == "technical":
            task = (f"为原始选题《{state.get('topic', '')}》写一篇读者能立即照做的教程。"
                    "全文围绕一个最小示例。让示例在一个代码块中自行构造最小输入并打印结果。"
                    "解释为什么这个输入能检验题中的每个要求；给出读者能核对的具体结果。"
                    "只说明这个示例实际使用的接口与行为，并在解释句末给出相应文档编号。"
                    "不介绍可选参数、其他工具或底层实现，除非解题需要且有直接原文依据。"
                    "描述返回值或实现时要说清适用的配置。可直接从这个例子看出的现象以例中输出为依据。"
                    f"已定标题如下：\n# {state.get('selected_title', '')}\n逐行保留章节：\n{outline_text}\n"
                    f"目标 {target_words} 字（含代码共 {lower_words}–{upper_words} 个非空白可见字符）。直接输出 Markdown。")
        if review_feedback:
            headings = "\n".join(line for line in outline_text.splitlines()
                                 if re.match(r"^#{2,3}\s", line) or "<!-- 配图" in line)
            if (state.get("review_count") or 0) >= 2:
                # Repeated rejection: an independent redraft avoids copying the rejected passage.
                review_section = "上一稿返修后仍未达标，请依照原任务和审稿意见重新起草。\n" + review_feedback
            task = (f"修订下列退稿，直接交付完整 Markdown。第一行是 # {state.get('selected_title') or ''}\n"
                    f"沿用以下章节标题、顺序和配图标记。正文连同代码和标题共 {lower_words}–{upper_words} 个非空白字符，"
                    f"瞄准 {target_words} 字。请逐行复制下面的章节标题，包括每行开头的井号数。\n"
                    f"{headings}\n以作者原始选题为验收条件，保留稿中成立的内容。此前的策划、摘要与旧稿都可能出错；"
                    "删去不能从实际材料推出的数字、普遍断言和经历。仅使用后附来源，引用紧邻被支持的分句。"
                    "其他编辑意见见下文。\n" + review_section)
            if state.get("article_style") == "technical":
                task += "\n编程操作只用一个最小例子，不要在代码、样本和输出中重复粘贴相同数据。"
        if short_brief(state) and state.get("article_style") == "technical":
            task += ("\n如果题目要求操作真实文件，示例要准备输入并演示如何读入这个文件，或者明确说明如何把内存示例换成读文件。"
                     "用示例的实际输出验证每一项需求。描述默认用法时限定于示例配置，不要断言所有可选配置行为相同。")
        if state.get("evidence_questions"):
            task += ("\n【研究员逐问定位的页面】下列对应关系是检索索引。写每一节时，对照该问题对应页面的原文；"
                     "不支持时不要沿用编号。同机构的其他页面不可互换。\n" + (state.get("content_research") or ""))
        if short_brief(state) and state.get("article_style") == "popular_science":
            task += ("\n说明从什么位置观察、比较哪两个对象。示意图中的理想情况不自动成为现象发生的必要条件。"
                     "原文说大致、附近或可能时保留这些限定。例子要帮助解释原题中的现象。")
        # 首次写作：合并输出「写作思路 + 正文」；打回重跑时只输出正文
        evidence_state = state
        questions = state.get("evidence_questions") or []
        if questions and all(q.get("status") in {"opened", "existing"} for q in questions):
            matched_urls = {q["url"] for q in questions}
            focused = [s for s in state.get("evidence_sources", []) if s["url"] in matched_urls]
            if {s["url"] for s in focused} == matched_urls:
                evidence_state = {**state, "evidence_sources": focused}
        task += editorial_brief(state) + evidence_prompt(evidence_state)
        if not review_feedback and not short_brief(state):
            task += "\n" + GENERATE_CONTENT_THOUGHTS_ADDON.format(
                thoughts_marker=THOUGHTS_MARKER,
                content_marker=CONTENT_MARKER,
            )

        resp = str(model.invoke([("system", GENERATE_CONTENT_SYSTEM), ("human", task)]).content)
        thoughts, content = split_thoughts_and_content(resp)
        if not content:
            raise ValueError("写手未返回正文，请重新生成。")
        if short_brief(state) and state.get("selected_title"):
            # Title selection is already complete. The writer owns the section bodies.
            body = re.sub(r"\A {0,3}# [^\n]*(?:\n|\Z)", "", content, count=1).lstrip()
            content = f"# {state['selected_title']}\n\n{body}"
        return {**refreshed, "content": content, "writing_thoughts": thoughts or state.get("writing_thoughts") or ""}

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
            ) + ("\n原始选题：" + str(s.get("topic") or "") + "。逐项覆盖原题的各个问题，一次可打开多个原页。"
                 "每个问题均要找到直接解释它的原文，检索词使用发布者的语言。"
                 "事实稿须调用 read_web_sources 打开原页。若知道具体官方页面可直接打开；只知道机构时用 web_search 的 site 参数找页面再打开。"
                 if requires_sources(s) else ""),
            tools=RESEARCH_TOOLS,
            model_role="researcher",
            temperature=0.3,
        ),
    )
    builder.add_node("research_tools", make_react_tools_node(RESEARCH_TOOLS))
    builder.add_node("research_summary", make_content_research_summary_node())

    # ---- 生成段：写手 ----
    builder.add_node("content_generate", make_content_generate_node())
    builder.add_node("author_material", lambda s: {
        "content_research": "仅使用作者简报中给出的观察和意向。可用条件句举例，客观效果不在本次素材范围内。",
        "evidence_sources": [],
    })

    # ---- 边 ----
    builder.add_conditional_edges(
        START,
        lambda s: "author_material" if personal_reflection(s) else (
            "content_generate" if s.get("content_research") and s.get("review_count")
            and not s.get("research_suggestions") else "research_start"),
        ["content_generate", "research_start", "author_material"],
    )
    builder.add_edge("research_start", "research_plan")
    builder.add_conditional_edges(
        "research_plan",
        has_tool_calls,
        {"tools": "research_tools", "done": "research_summary"},
    )
    builder.add_edge("research_tools", "research_plan")
    builder.add_edge("research_summary", "content_generate")
    builder.add_edge("author_material", "content_generate")
    builder.add_edge("content_generate", END)

    return builder.compile()


if __name__ == "__main__":
    # 本地冒烟：docker exec 内直接跑，验证正文链路（调研 + 写作）
    graph = build_content_graph()
    from src.blog_agent.clients.provider_budget import provider_run

    with provider_run():
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
