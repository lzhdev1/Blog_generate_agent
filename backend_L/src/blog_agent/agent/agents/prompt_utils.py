"""
prompt 辅助工具：文章风格/专业水平/字数 的映射与描述拼接

被 outline_graph / content_graph / supervisor_graph 的 task_builder 共用，
保持各阶段对同一用户配置的描述口径一致（与旧版 backend 的 style_map/level_map 对齐）。
"""
import re
from typing import Optional

from src.blog_agent.agent.state import AgentState

IMAGE_MARKER_RE = re.compile(r"<!--[ \t]*配图[：:][ \t]*([^\s<>][^<>\r\n]*?)[ \t]*-->")

# 文章风格 -> 中文描述（标题选择页配置，传大纲子图）
STYLE_DESC_MAP = {
    "popular_science": "科普类（通俗易懂，面向大众读者，结构轻松有趣）",
    "technical": "技术类（有技术深度，面向有基础的读者）",
    "essay": "论文类（学术严谨，论证严密）",
    "prose": "散文类（文笔优美，抒情叙事）",
    "note": "笔记类（简洁实用，要点清晰）",
}

# 专业水平 -> 中文描述（大纲确认页配置，传正文子图）
LEVEL_DESC_MAP = {
    "general": "入门科普，语言通俗易懂，避免过多专业术语，适合零基础读者",
    "medium": "中等深度，有一定技术细节，但不过于晦涩，适合有基础的读者",
    "advanced": "高级深度，包含较多技术细节和原理分析，适合进阶读者",
    "professional": "专业级，深入技术原理，包含代码/配置/架构分析，适合专业从业者",
}


def style_desc(state: AgentState) -> str:
    """从 state 解析文章风格的中文描述（custom 时用用户输入）"""
    style = state.get("article_style") or ""
    if style == "custom":
        custom = (state.get("article_style_custom") or "").strip()
        return f"自定义风格：{custom}" if custom else "自定义风格"
    return STYLE_DESC_MAP.get(style, "")


def level_desc(level: Optional[str]) -> str:
    """专业水平的中文描述"""
    if not level:
        return ""
    return LEVEL_DESC_MAP.get(level, level)


def editorial_brief(state: AgentState) -> str:
    """Keep the same author brief in research, writing and review from the first title."""
    fields = [("原始选题", state.get("topic")), ("创作目的", state.get("purpose")),
              ("目标读者", level_desc(state.get("level"))), ("文章风格", style_desc(state)),
              ("目标字数", state.get("word_count")), ("作者给大纲的补充", state.get("extra_requirements")),
              ("作者给正文的补充", state.get("content_extra_requirements"))]
    lines = [f"{label}：{value}" for label, value in fields if value]
    style = state.get("article_style")
    if style == "technical":
        lines.append("编程操作题按读者能否照做验收。拟题与检索聚焦指定工具，"
                     "大纲给输入、可执行的最小代码、可核对的输出留位置；比较其他工具需有作者需求。")
    elif style == "popular_science":
        lines.append("原始选题中的每个主要问题都要回答。以解释现象为先，"
                     "与解答无关的频率、纪录和精确测量可以省略。")
    elif style == "note":
        lines.append("作者要求个人笔记时，保留第一人称的视角。围绕本人如何选择、打算怎么做或还拿不准什么来写。"
                     "只有选题、没有实际观察时，用设想和例子。不要从同类热文引入面向大众的心理疗效、诊断或行为干预。")
    if state.get("word_count") and state["word_count"] <= 600:
        lines.append("短稿宜只设两三个同级小节。将必要的引入与收束写进这些小节，"
                     "没有必要为背景、步骤和总结各设多层标题。")
    if lines and state.get("article_style") in {None, "", "note", "prose", "custom"}:
        lines.append("涉及第一人称时，以作者在上述输入中提供的经历和创作授权为准。只有选题时，"
                     "可以写个人取舍、打算、比喻或明确假设，不要补写成已发生的见闻。"
                     "确实给了亲历素材，就在其范围内写；明确要求虚构时，可按设定创作。"
                     "检索结果、候选标题、策划大纲和模型写过的段落都不能证明作者亲历。")
    return "\n\n【作者的创作简报】\n" + "\n".join(lines) if lines else ""


# 字数硬标准：目标字数上下浮动不得超过该值（单位：字）
WORD_COUNT_TOLERANCE = 100


def word_count_bounds(word_count: Optional[int]) -> tuple[int, int]:
    """返回字数硬性区间 (下限, 上限)：目标字数 ±100 字。

    未指定目标字数时按默认 800 字处理，保证所有任务都有明确区间。
    """
    target = word_count if word_count and word_count > 0 else 800
    lower = max(1, target - WORD_COUNT_TOLERANCE)
    upper = target + WORD_COUNT_TOLERANCE
    return lower, upper


def word_count_requirement(word_count: Optional[int]) -> str:
    """字数要求描述（给写手的任务指令，硬标准）"""
    target = word_count if word_count and word_count > 0 else 800
    lower, upper = word_count_bounds(target)
    return (
        f"字数要求（硬标准）：全文严格控制在 {lower}-{upper} 字"
        f"（目标 {target} 字，上下浮动不得超过 {WORD_COUNT_TOLERANCE} 字）；"
        "按正文可见文字、标点和代码计数，空白、配图、来源编号、链接目标与常用排版标记不计。"
    )
