"""Word-range repair shared by the interactive worker and the unattended graph."""
import json
import re

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field, ValidationError

from src.blog_agent.agent.agents.prompt_utils import word_count_bounds
from src.blog_agent.agent.evidence import indexed_sentences
from src.blog_agent.agent.agents.short_brief import short_brief
from src.blog_agent.agent.agents.writer_prompts import WORD_COUNT_FIX_TASK, WORD_COUNT_TRIM_TASK
from src.blog_agent.agent.nodes.quality_gate import count_chars, title_preserved
from src.blog_agent.clients.llm_client import bind_structured_output, chat


def _strip_code_fence(text: str) -> str:
    """去掉模型偶尔包裹的 Markdown 代码块围栏"""
    text = (text or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


# Length-only changes must preserve qualifications, comparison scope and source references.
_QUALIFIER = re.compile(
    r"仅|只(?:有|测|限|在|针对|适用|涵盖)|尚未|仍未|仍然未知|前提|除非|并非|不代表|不适用|不适用于|"
    r"不能(?:据此|推广)|不确定|样本(?:有限|仅)|\b(?:only|unless|except|limited to|does not apply)\b|"
    r"\[S\d+\]",
    re.IGNORECASE,
)


_FENCE = re.compile(r"(?ms)^ {0,3}(?P<fence>`{3,}|~{3,})[^\n]*\n.*?^ {0,3}(?P=fence)[ \t]*(?=\n|$)")
_SPAN = re.compile(_FENCE.pattern + r"|^ {0,3}#{1,6}[ \t]+[^\n]+|[^\n。！？!?；;]+[。！？!?；;]?", re.S | re.M)


def _lock_passages(content):
    """Give the editor stable anchors for code, section names and evidential qualifications."""
    locked = {}
    prefix = "⟦原文"
    while prefix in content:
        prefix += "段"

    def replace(match):
        value = match.group()
        if not (match.group("fence") or value.lstrip().startswith("#") or _QUALIFIER.search(value)):
            return value
        token = f"{prefix}{len(locked) + 1}⟧"
        locked[token] = value
        return token

    return _SPAN.sub(replace, content), locked


class PassageEdit(BaseModel):
    slot: int = Field(ge=1, description="可编辑位置编号")
    text: str = Field(description="此位置的新文字。替换位置可用空字符串删除冗余；追加位置只填新增的说明。")
    evidence_address: str = Field(default="", description="事实性补写选择支持新增说明的原句编号，如 @S2.4；无需引证时留空")


class PassageEdits(BaseModel):
    edits: list[PassageEdit] = Field(description="只返回需要修改的位置，每个编号最多一次。")


_LOCAL_SPAN = re.compile(
    _FENCE.pattern.replace(r"(?=\n|$)", r"\r?(?=\n|$)")
    + r"|^ {0,3}#{1,6}[ \t]+[^\r\n]+|(?:`+[^`\r\n]*`+|[^\r\n。！？!?；;`])+[。！？!?；;]?",
    re.M | re.S)


def _edit_slots(content, expand):
    slots = []
    for match in _LOCAL_SPAN.finditer(content):
        raw = match.group()
        value = raw.strip()
        if (not value or match.group("fence") or value.startswith(("#", "|", "![", "<!--", "[S"))
                or not re.search(r"[\w\u4e00-\u9fff]", value)):
            continue
        start = match.start() + len(raw) - len(raw.lstrip())
        end = start + len(value)
        protected = _QUALIFIER.search(value) or "`" in value or "](" in value or "://" in value
        if not protected:
            slots.append((start, end, "替换", value))
        elif expand and value.endswith(("。", "？", "！", ".", "?", "!")) and (
                end == len(content) or content[end:].startswith(("\n", "\r\n"))):
            slots.append((end, end, "段后追加", value))
    return slots


def _edit_short_factual_body(state, content, lower, upper):
    """Apply bounded local edits; never ask the model to reproduce protected passages."""
    writer = bind_structured_output(PassageEdits, role="writer", temperature=0.2, enable_thinking=False)
    for _ in range(2):
        length = count_chars(content)
        expand = length < lower
        slots = _edit_slots(content, expand)
        if not slots:
            break
        if not expand and count_chars(content) - sum(count_chars(s[3]) for s in slots) > upper:
            break
        goal = min(upper, lower + 25) if expand else max(lower, upper - 25)
        menu = [(i, mode, text) for i, (_, _, mode, text) in enumerate(slots, 1)]
        human = (f"当前 {length} 字；请净{'增加' if expand else '删减'}约 {abs(length-goal)} 字，"
                 f"最终必须在 {lower}–{upper} 字。\n全文供理解上下文：\n{content}\n"
                 "可以操作的位置（编号、操作、当前句或追加前的句子）：\n" + json.dumps(menu, ensure_ascii=False))
        anchors = {}
        if expand and state.get("article_style") == "popular_science":
            targets = {q.get("url") for q in state.get("evidence_questions", [])}
            for source in state.get("evidence_sources") or []:
                if not targets or source["url"] in targets:
                    anchors.update(indexed_sentences(source))
            if state.get("evidence_sources") and not anchors:
                break
        if anchors:
            human += ("\n每项新增解释须由其中一句原文直接支持，并填写 evidence_address，程序负责标注。"
                      "只补足本节题目需要的因果和观察关系，保留条件与范围，不增设额外的必要条件。\n"
                      + json.dumps(anchors, ensure_ascii=False))
        try:
            report = writer.invoke([("system", "你是短事实稿的文字编辑。只返回编号和新文字；替换普通句时可删冗，"
                "也可沿现有材料在原句后多写两句自足的说明。段后追加只写新增文字。"
                "用已有输入、条件、结果或区别解释读者能检查什么，不引入新的事实、术语、引用、代码或标题。"), ("human", human)])
        except (ValidationError, OutputParserException):
            continue
        if not report or not report.edits:
            continue
        edits = {e.slot: e.text.strip() for e in report.edits}
        if (len(edits) != len(report.edits) or any(i > len(slots) for i in edits)
                or any(re.search(r"(?m)^\s*#|\[S\d+\]|```|~~~", text) for text in edits.values())):
            continue
        if anchors:
            if any(e.text.strip() and e.evidence_address not in anchors for e in report.edits):
                continue
            for e in report.edits:
                if edits[e.slot]:
                    ref = e.evidence_address[1:].split(".")[0]
                    edits[e.slot] = edits[e.slot].rstrip("。") + f"[{ref}]。"
        candidate = content
        for i in sorted(edits, reverse=True):
            start, end, mode, _ = slots[i-1]
            value = edits[i]
            if mode == "段后追加" and value:
                value = "\n\n" + value
            candidate = candidate[:start] + value + candidate[end:]
        if not title_preserved(state.get("selected_title") or "", candidate):
            continue
        actual = count_chars(candidate)
        if lower <= actual <= upper:
            state["content"] = candidate
            return True, True
        if abs(goal-actual) < abs(goal-length):
            content = candidate
    return False, False


def rewrite_to_word_range(state: dict) -> tuple[bool, bool]:
    """字数硬校验：正文必须落在 目标字数 ±100 字。

    - 初始已在区间内：返回 (True, False)，不调用模型
    - 超出区间：最多强制修正 2 次，返回 (最终是否达标, 是否改动过正文)
    """
    target = state.get("word_count") or 800
    lower, upper = word_count_bounds(target)
    content = state.get("content") or ""
    original_content = content
    changed = False

    outline = state.get("outline") or ""
    heading_count = len(re.findall(r"^#{2,3}\s", outline, re.M)) or 1
    per_heading_words = max(20, target // heading_count)

    if lower <= count_chars(content) <= upper:
        return True, False
    if short_brief(state) and state.get("article_style") in {"technical", "popular_science"}:
        return _edit_short_factual_body(state, content, lower, upper)
    marked, locked = _lock_passages(original_content)
    if count_chars("\n".join(locked.values())) > upper:
        return False, False
    legend = "\n".join(f"{token} 还原为：{value}" for token, value in locked.items())

    for attempt in range(2):
        actual = count_chars(content)
        if lower <= actual <= upper:
            state["content"] = content
            return True, changed

        over = max(0, actual - upper)
        if actual > upper and (attempt > 0 or over <= 300):
            prompt = WORD_COUNT_TRIM_TASK.format(
                actual=actual,
                upper=upper,
                lower=lower,
                over=over,
                content=marked,
            )
        else:
            prompt = WORD_COUNT_FIX_TASK.format(
                lower=lower,
                upper=upper,
                target=target,
                actual=actual,
                delete_words=max(0, actual - upper),
                heading_count=heading_count,
                per_heading_words=per_heading_words,
                outline=outline,
                content=marked,
            )

        if locked:
            prompt += ("\n保留正文内的每个占位符及其顺序。系统会还原原文并统计字数。"
                       "编辑未锁定部分；接近目标字数时优先收束，不要重复引文和代码。\n" + legend)
        fixed = chat(prompt, role="writer", temperature=0.3)
        candidate = _strip_code_fence(fixed)
        # Some providers reproduce a protected passage verbatim instead of emitting its marker.
        for token, value in locked.items():
            if token not in candidate and candidate.count(value) == 1:
                candidate = candidate.replace(value, token, 1)
        if not candidate or any(candidate.count(token) != 1 for token in locked):
            continue
        if list(locked) != sorted(locked, key=candidate.index):
            continue
        next_marked = candidate
        for token, value in locked.items():
            candidate = candidate.replace(token, value)
        if not title_preserved(state.get("selected_title") or "", candidate):
            continue
        content = candidate
        marked = next_marked
        changed = True
        if lower <= count_chars(content) <= upper:
            state["content"] = content
            return True, changed

    # Keep the checkpointed draft. The gate reports the length issue and the normal
    # revision loop (or author) receives the entire argument, including its caveats.
    return False, False
