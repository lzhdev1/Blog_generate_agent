"""
工具统一出口：所有 langchain @tool 从这里导出，供 ReAct 子图绑定。

用法：
    from src.blog_agent.agent.tools import ALL_TOOLS
    agent = create_react_agent(model=..., tools=ALL_TOOLS, ...)
"""
from src.blog_agent.agent.tools.format_tool import (
    dumps_json,
    format_markdown,
    format_markdown_tool,
    to_json,
)
from src.blog_agent.agent.tools.image_tool import generate_image, search_image
from src.blog_agent.agent.tools.search_tool import web_search

# 绑定给 ReAct 循环的全部工具
ALL_TOOLS = [
    web_search,
    search_image,
    generate_image,
    format_markdown_tool,
    to_json,
]

__all__ = [
    "ALL_TOOLS",
    "web_search",
    "search_image",
    "generate_image",
    "format_markdown",
    "format_markdown_tool",
    "to_json",
    "dumps_json",
]
