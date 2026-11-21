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
import re
from urllib.parse import urlsplit

import httpx
from langchain_core.tools import tool

from config.settings import settings
from src.blog_agent.agent.evidence import safe_source_url
from src.blog_agent.clients.provider_budget import http

# 博查 Web Search API（国内直连）
_BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"

# 单次返回结果条数
_COUNT = 8
# 请求超时（秒）
_TIMEOUT = 15
_DNS_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_DOMAIN = re.compile(rf"(?:{_DNS_LABEL}\.)+{_DNS_LABEL}")


@tool
def web_search(query: str, freshness: str = "noLimit", site: str = "") -> dict:
    """
    联网搜索实时资料。当需要时效性强的事实、数据、新闻、同类文章时调用。

    Args:
        query: 搜索查询语句（建议用具体、完整的问题或关键词组合）
        freshness: 时效范围过滤，可选 oneDay / oneWeek / oneMonth / oneYear /
                   noLimit（默认不限时间）
        site: 可选的单个机构或文档域名，不含协议或路径。指定后只返回该站点及子域的网页。

    Returns:
        status 为 ok / empty / unavailable；sources 仅包含实际检索得到的原始记录。
    """
    if not settings.bocha_api_key:
        return {"status": "unavailable", "reason": "not_configured", "sources": []}

    if not query.strip() or len(query) > 512:
        return {"status": "unavailable", "reason": "invalid_query", "sources": []}
    site = site.strip().lower().removesuffix(".")
    if site and (len(site) > 253 or not _DOMAIN.fullmatch(site)):
        return {"status": "unavailable", "reason": "invalid_site", "sources": []}
    payload = {
        "query": query,
        "count": _COUNT,
        "summary": True,
        "freshness": freshness,
    }
    if site:
        payload["include"] = site
    try:
        resp = http.post(
            _BOCHA_ENDPOINT,
            json=payload,
            headers={
                "Authorization": f"Bearer {settings.bocha_api_key}",
                "Content-Type": "application/json",
            },
            timeout=_TIMEOUT,
            extensions={"provider_kind": "search"},
        )
    except httpx.HTTPError:
        return {"status": "unavailable", "reason": "network", "sources": []}

    if resp.status_code != 200:
        return {"status": "unavailable", "reason": f"http_{resp.status_code}", "sources": []}
    try:
        body = resp.json()
        if body.get("code", 200) not in (200, "200"):
            return {"status": "unavailable", "reason": "provider", "sources": []}
        pages = ((body.get("data") or {}).get("webPages") or {}).get("value") or []
        if not isinstance(pages, list):
            raise ValueError("unexpected search result type")
    except (AttributeError, ValueError):
        return {"status": "unavailable", "reason": "invalid_response", "sources": []}

    sources = []
    for item in pages[:_COUNT]:
        if not isinstance(item, dict):
            continue
        url = safe_source_url(item.get("url"))
        if site and url:
            host = urlsplit(url).hostname.lower().rstrip(".")
            if host != site and not host.endswith("." + site):
                continue
        snippet = str(item.get("snippet") or "").strip()
        summary = str(item.get("summary") or "").strip()
        # A provider's long summary is useful for discovery, but is not a verbatim
        # page extract. Keep the distinction when records reach the writer/reviewer.
        excerpt = (snippet or (f"【检索摘要】{summary}" if summary else ""))[:360]
        if url and excerpt:
            sources.append({
                "url": url, "title": str(item.get("name") or "")[:120] or url,
                "site": str(item.get("siteName") or "")[:60],
                "published": str(item.get("datePublished") or "")[:40], "excerpt": excerpt, "origin": "discovery",
            })
    return {"status": "ok" if sources else "empty", "sources": sources}
