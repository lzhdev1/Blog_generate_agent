"""
配图工具：搜图 / AI 生图

包装 clients/image_client（纯 I/O），以 langchain @tool 形式暴露给 ReAct 子图。
工具内部自动把远程图下载持久化到本地 /images/，返回本地 URL，
避免 AI 生图的 OSS 临时链接过期失效。
"""
from uuid import uuid4

from langchain_core.tools import tool

from src.blog_agent.clients.image_client import image_client


@tool
def search_image(keywords: str) -> str:
    """
    按关键词搜索图片（Pexels 优先、Unsplash 兜底），返回已持久化的图片 URL。

    Args:
        keywords: 英文搜索关键词，5-8 个单词，空格分隔（可直接用于图片库搜索）

    Returns:
        图片 URL（/images/... 本地地址）；搜索失败返回失败提示。
    """
    url = image_client.fetch_image(keywords, image_source="api")
    if not url:
        return "图片搜索失败：未找到合适图片"
    return image_client.persist_image(url, f"search_{uuid4().hex}")


@tool
def generate_image(prompt: str) -> str:
    """
    AI 生成图片（百炼 qwen-image / wanx），返回已持久化的图片 URL。

    Args:
        prompt: 专业英文 AI 绘画提示词（主体/风格/色调/构图/光线/氛围）

    Returns:
        图片 URL（/images/... 本地地址）；生成失败返回失败提示。
    """
    url = image_client.fetch_image(prompt, image_source="ai")
    if not url:
        return "图片生成失败：AI 生图未返回结果"
    return image_client.persist_image(url, f"generated_{uuid4().hex}")
