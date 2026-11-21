"""Compose a short Python walkthrough around a single observable result."""
import json
import re
from itertools import combinations

from pydantic import BaseModel, Field

from src.blog_agent.agent.agents.prompt_utils import editorial_brief, word_count_bounds
from src.blog_agent.agent.agents.short_brief import short_brief
from src.blog_agent.agent.evidence import render_sources
from src.blog_agent.agent.nodes.quality_gate import count_chars
from src.blog_agent.clients.llm_client import bind_structured_output


class TutorialSection(BaseModel):
    explanation: str = Field(min_length=1, description="独立成立的核心解释，保留必要条件、操作、输入与出处编号；不要标题")
    detail: str = Field(description="可整体省略的补充说明，保留自己的必要限定与引用；无需补充时留空")


class PythonWalkthrough(BaseModel):
    code: str = Field(min_length=1, description="读者可原样运行的一个完整 Python 脚本，不含围栏")
    stdout: str = Field(min_length=1, description="完整脚本的逐行标准输出原文，不带注释、前缀或围栏")
    sections: list[TutorialSection] = Field(min_length=1, max_length=3, description="严格按给定标题顺序，每节一个对象")


class PythonFileWalkthrough(PythonWalkthrough):
    file_usage: str = Field(min_length=1, description="必须保留的实操句。用完整、具体的 Python 调用告诉读者如何把示例用于磁盘上的真实文件；使用自己的路径时如何替换示例输入")


def _file_task(state):
    topic = state.get("topic") or ""
    return re.search(r"文件|\bfiles?\b", topic, re.I) and not re.search(r"仅.{0,4}内存|不要.{0,5}文件", topic)


def _headings(state):
    return re.findall(r"^ {0,3}#{2,3}[ \t]+\S[^\n]*", state.get("outline") or "", re.M)


def short_python_walkthrough(state):
    topic = state.get("topic") or ""
    return bool(short_brief(state) and state.get("selected_title") and state.get("article_style") == "technical"
            and re.search(r"\bpython(?:\s*3(?:\.\d+)*)?\b", topic, re.I | re.ASCII)
            and re.search(r"读取|写入|操作|处理|导出|导入|实现|使用|转换|解析|生成|构建|编写|绘制|运行|计算|排序|教程|how to", topic, re.I)
            and 1 <= len(_headings(state)) <= 3)


def _unfence(value):
    text = value.strip()
    match = re.fullmatch(r"```[^\n]*\n(.*)\n```", text, re.S)
    return match[1] if match else text


def _render(state, draft):
    headings = _headings(state)
    if len(draft.sections) != len(headings):
        raise ValueError("教程写手返回的章节数与已确认大纲不一致")
    explanation = [s.explanation.strip() for s in draft.sections]
    optional = [i for i, section in enumerate(draft.sections) if section.detail.strip()]
    target = state["word_count"]
    lower, upper = word_count_bounds(target)

    def format_article(include):
        parts = ["# " + state["selected_title"]]
        for i, heading in enumerate(headings):
            parts.extend([heading, explanation[i]])
            if i == 0:
                parts.extend(["```python\n" + _unfence(draft.code) + "\n```",
                              "运行结果", "```text\n" + _unfence(draft.stdout) + "\n```"])
                if isinstance(draft, PythonFileWalkthrough):
                    parts.append(draft.file_usage.strip())
            if i in include:
                parts.append(draft.sections[i].detail.strip())
        return "\n\n".join(parts)

    variants = (format_article(indices) for size in range(len(optional) + 1)
                for indices in combinations(optional, size))

    def rank(article):
        length = count_chars(article)
        return max(lower - length, length - upper, 0), abs(length - target)

    return min(variants, key=rank)


def write_short_tutorial(state):
    questions = state.get("evidence_questions") or []
    urls = {item.get("url") for item in questions if item.get("status") in {"opened", "existing"}}
    sources = state.get("evidence_sources") or []
    if urls and all(item.get("status") in {"opened", "existing"} for item in questions):
        sources = [source for source in sources if source["url"] in urls]
    section_budget = max(20, min(120, state["word_count"] // (len(_headings(state)) + 4)))
    task = (editorial_brief(state) + "\n已确认小节：\n" + "\n".join(_headings(state))
            + "\n研究员逐问定位的网页：\n" + json.dumps(questions, ensure_ascii=False)
            + "\n实际网页摘录：\n" + render_sources(sources)
            + f"\n每个核心段约 {section_budget} 个汉字，用实际对应的 [S编号] 支撑外部事实。每节补充段另写约 {section_budget} 字，"
              "可以独立省略，仍须有用，例如怎样核对结果与如何替换输入。不要把必要步骤和限定词放在补充段。"
              "只给一个 3–7 行的小脚本，用同一份最小数据同时演示原题所有要求。"
              "要求读文件时，程序自行创建实际样本文件再读取；或使用内存输入并在核心段明确展示换成真实文件的写法。"
              "输出简短，按 print 的实际格式逐行写全。第二节解释输出中的具体值如何验证另一个要求。"
              "只解释脚本使用的默认配置及文档能直接支持的行为。不要概括其他模式的所有例外或引入其他工具。"
              "核心段连同脚本、输出、章节名应比目标短约 80 字；读者仅凭核心段和代码就能复现。"
              "代码、输出和小节分别填入指定字段，不在段落中重复粘贴它们。")
    if state.get("review_feedback"):
        task += "\n上一轮的核验意见：\n" + state["review_feedback"]
    schema = PythonFileWalkthrough if _file_task(state) else PythonWalkthrough
    if schema is PythonFileWalkthrough:
        task += ("\n文件操作的必需步骤独立放入 file_usage，限定 35–65 个字。若代码以内存对象演示，"
                 "明确给出用真实文件路径、打开方式和必要参数替换它的具体调用。该句与示例使用相同的变量名。")
    writer = bind_structured_output(schema, role="writer", temperature=0.3, enable_thinking=False)
    result = writer.invoke([("system", "你写简明、可运行的 Python 实操教程。只使用作者选题、实际网页和示例输出。"), ("human", task)])
    if result is None:
        raise ValueError("教程写手未返回代码与讲解")
    return {"content": _render(state, result), "writing_thoughts": state.get("writing_thoughts") or ""}
