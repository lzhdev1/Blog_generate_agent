"""
搜索工具：联网搜索实时资料

实现方式：调用博查 Web Search API（国内直连、专为 AI 设计的结构化搜索），
以 langchain @tool 的形式暴露给 ReAct 子图。模型在 ReAct 循环中显式调用
本工具获取时效性资料，工具内部发起一次 HTTP 搜索请求并返回结构化结果。

为什么这样实现：
- 千问自带联网搜索（enable_search）虽可用，但单次 10-30s、慢且贵，且
  Chat Completions 返回不带结构化来源（标题/URL/发布时间）；
- 博查国内直连、约 0.1s 极速，返回标题/URL/站点/发布时间/摘要，正好满足
  调研结果需标注"资料来源与时间"的需求；
- 工具边界清晰：未来替换为 Tavily / SerpAPI 等独立搜索 API 时，只改本文件，
  ReAct 循环与 prompt 无需变动。
"""
import requests
from langchain_core.tools import tool

from config.settings import settings

# 博查 Web Search API（国内直连）
_BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"

# 搜索结果的单次最大字符数（防止过长的搜索摘要撑爆上下文）
_MAX_RESULT_CHARS = 4000
# 单次返回结果条数
_COUNT = 8
# 请求超时（秒）
_TIMEOUT = 15


@tool
def web_search(query: str, freshness: str = "noLimit") -> str:
    """
    联网搜索实时资料。当需要时效性强的事实、数据、新闻、同类文章时调用。

    Args:
        query: 搜索查询语句（建议用具体、完整的问题或关键词组合）
        freshness: 时效范围过滤，可选 oneDay / oneWeek / oneMonth / oneYear /
                   noLimit（默认不限时间）

    Returns:
        搜索结果文本（含标题、来源、发布时间与摘要），超长时截断。
    """
    if not settings.bocha_api_key:
        return "搜索失败：未配置 bocha_api_key，请先在 backend_L/.env 中填写博查 API Key。"

    payload = {
        "query": query,
        "count": _COUNT,
        "summary": True,
        "freshness": freshness,
    }
    try:
        resp = requests.post(
            _BOCHA_ENDPOINT,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.bocha_api_key}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        return f"搜索失败：网络请求异常（{e.__class__.__name__}），请稍后重试。"

    if resp.status_code != 200:
        # 常见错误：401 key 无效 / 403 余额不足 / 429 限流
        return f"搜索失败：HTTP {resp.status_code} - {resp.text[:200]}"

    resp_json = resp.json()
    # 博查响应结构：{"code":200, "data": {"_type":"SearchResponse", "webPages": {"value":[...]}}}
    data = resp_json.get("data") or {}
    pages = (data.get("webPages") or {}).get("value") or []
    if not pages:
        return "未搜索到相关结果，请尝试换一个关键词或调整 freshness 时间范围。"

    lines = []
    for i, item in enumerate(pages, 1):
        title = item.get("name", "")
        url = item.get("url", "")
        site = item.get("siteName", "")
        published = item.get("datePublished", "")
        snippet = (item.get("summary") or item.get("snippet") or "").strip()
        meta = " | ".join(
            filter(None, [site, f"发布时间:{published}" if published else "发布时间:未知"])
        )
        lines.append(f"{i}. {title}\n   链接: {url}\n   来源: {meta}\n   摘要: {snippet}")
    return "\n\n".join(lines)[:_MAX_RESULT_CHARS]
