"""
prompt 辅助工具：文章风格/专业水平/字数 的映射与描述拼接

被 outline_graph / content_graph / supervisor_graph 的 task_builder 共用，
保持各阶段对同一用户配置的描述口径一致（与旧版 backend 的 style_map/level_map 对齐）。
"""
from typing import Optional

from src.blog_agent.agent.state import AgentState

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


def word_count_requirement(word_count: Optional[int]) -> str:
    """字数要求描述（给写手的任务指令）"""
    if word_count and word_count > 0:
        return f"字数要求：全文 {word_count} 字左右，上下浮动不超过 10%。"
    return "字数要求：全文不少于 800 字。"
