"""Read bounded, attributable passages from public HTTPS pages."""
from collections import Counter
from contextlib import closing
from html.parser import HTMLParser
import ipaddress
import math
import re
import socket
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from langchain_core.tools import tool

from src.blog_agent.agent.evidence import safe_source_url
from src.blog_agent.clients.provider_budget import http


class UnreadablePage(ValueError):
    pass


def _public_address(host):
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9-]+\.)+[a-z][a-z0-9-]+", host, re.I):
        raise UnreadablePage("invalid_host")
    addresses = [ipaddress.ip_address(addr[4][0]) for addr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    # Transparent DNS proxies may return only benchmark-network aliases. Resolve independently
    # in that case, then connect to a public IP with the original TLS server name.
    benchmark = (ipaddress.ip_network("198.18.0.0/15"), ipaddress.ip_network("2001:2::/48"))
    if addresses and all(any(a in network for network in benchmark) for a in addresses):
        result = http.get("https://dns.google/resolve", params={"name": host, "type": "A"}, timeout=6,
                          extensions={"provider_kind": "source_dns"})
        result.raise_for_status()
        addresses = [ipaddress.ip_address(a["data"]) for a in result.json().get("Answer", []) if a.get("type") == 1]
    if not addresses or any(not a.is_global or a.is_multicast for a in addresses):
        raise UnreadablePage("nonpublic_address")
    return str(sorted(addresses, key=lambda a: a.version)[0])


class _ArticleText(HTMLParser):
    blocks = {"p", "li", "dt", "dd", "tr", "pre", "blockquote", "h1", "h2", "h3", "h4"}
    excluded = {"script", "style", "nav", "footer", "template", "noscript", "svg", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.stack = []
        self.text = []
        self.passages = []
        self.title = ""
        self.in_title = False

    def flush(self):
        value = " ".join("".join(self.text).split())
        if len(value) >= 24:
            self.passages.append(value)
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in self.excluded:
            self.hidden.append(tag)
        if self.hidden:
            return
        if tag == "title":
            self.in_title = True
        if tag in self.blocks:
            self.flush()
            self.stack.append(tag)
        elif tag == "br":
            self.text.append(" ")

    def handle_endtag(self, tag):
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag == "title":
            self.in_title = False
        if tag in self.blocks and tag in self.stack:
            self.flush()
            self.stack = self.stack[:len(self.stack)-1-self.stack[::-1].index(tag)]

    def handle_data(self, data):
        if not self.hidden:
            if self.in_title:
                self.title += data
            if self.stack:
                self.text.append(data)


def _words(text):
    words = set(re.findall(r"[a-z][a-z0-9_]{2,}", text.lower()))
    words -= {"the", "and", "for", "that", "with", "are", "what", "why", "how", "org", "html", "http", "https"}
    for group in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(group[i:i+2] for i in range(len(group)-1))
    return words


def select_pages(candidates, requested_urls, keywords):
    """Honor the researcher's page choices before filling free slots from discovery."""
    queries = [_words(query) for query in keywords if query]

    def relevance(row):
        title = _words(row.get("title") or "")
        excerpt = _words(row.get("excerpt") or "")
        best = max(((2 * len(title & q) + len(excerpt & q)) / len(q) for q in queries if q), default=0)
        host = urlsplit(row["url"]).hostname or ""
        primary = host.startswith("docs.") or bool(re.search(r"\.(?:gov|edu)(?:\.[a-z]{2})?$", host))
        return best + (0.5 if primary else 0)

    ranked = sorted(candidates.values(), key=relevance, reverse=True)
    urls = [*requested_urls, *(item["url"] for item in ranked)]
    return list(dict.fromkeys(u for u in urls if safe_source_url(u).startswith("https://")))[:3]


def matching_candidate(candidates, keywords):
    """Reuse a known page only for a strong match; a shared broad noun is insufficient."""
    query = _words(keywords)
    for url in select_pages(candidates, [], [keywords]):
        row = candidates[url]
        title = _words(row.get("title") or "")
        terms = title | _words(row.get("excerpt") or "")
        if len(query & title) >= 2 and len(query & terms) >= max(3, math.ceil(len(query) * .7)):
            return url
    return ""


def _excerpt(paragraphs, keywords):
    # Work with intact sentences, so a long section cannot hide the actual matching text.
    windows = []
    for paragraph in dict.fromkeys(paragraphs):
        chunk = ""
        for sentence in re.split(r"(?<=[。！？])|(?<=[.!?])\s+", paragraph):
            if len(chunk) + len(sentence) > 780 and chunk:
                windows.append(chunk)
                chunk = ""
            if len(sentence.strip()) <= 780:
                chunk = (chunk + " " + sentence.strip()).strip()
        if chunk:
            windows.append(chunk)
    if not windows:
        return ""
    query = _words(keywords)
    matches = [_words(w) & query for w in windows]
    freq = Counter(word for words in matches for word in words)
    terms = re.findall(r"[a-z0-9_]+", keywords.casefold())
    # A phrase can identify the requested phenomenon more precisely than its loose component words.
    phrases = {" ".join(terms[i:i+n]) for n in (2, 3) for i in range(len(terms)-n+1)
               if all(w in query for w in terms[i:i+n])}
    def relevance(i):
        tokens = " " + " ".join(re.findall(r"[a-z0-9_]+", windows[i].casefold())) + " "
        phrase_score = sum(len(p.split()) * 2 for p in phrases if f" {p} " in tokens)
        return phrase_score + sum(math.log1p(len(windows)/freq[w]) for w in matches[i])
    ranked = sorted(range(len(windows)), key=relevance, reverse=True)
    best = []
    for i in ranked:
        if best and not matches[i]:
            break
        if sum(len(windows[j])+5 for j in best) + len(windows[i]) <= 1800:
            best.append(i)
        if len(best) == 4:
            break
    return "\n[…]\n".join(windows[i] for i in sorted(best))


def read_page(url, keywords):
    for _ in range(3):
        parts = urlsplit(safe_source_url(url))
        if parts.scheme != "https" or not parts.hostname or parts.port not in (None, 443):
            raise UnreadablePage("public_https_required")
        original = httpx.URL(url).copy_with(fragment=None)
        address = _public_address(original.host)
        request = httpx.Request("GET", original.copy_with(host=address),
                                headers={"Host": original.host, "Connection": "close", "User-Agent": "FolioResearch/1.0"},
                                extensions={"provider_kind": "source_page", "sni_hostname": original.host,
                                            "timeout": dict.fromkeys(("connect","read","write","pool"), 8)})
        # Explicit request keeps all provider cookies, credentials and proxy headers out of article requests.
        with closing(http.send(request, stream=True, follow_redirects=False)) as response:
            if response.is_redirect:
                url = urljoin(url, response.headers.get("location", ""))
                continue
            response.raise_for_status()
            media = response.headers.get("content-type", "").lower()
            if "text/html" not in media and "application/xhtml+xml" not in media and "text/plain" not in media:
                raise UnreadablePage("unsupported_content_type")
            data = bytearray()
            for chunk in response.iter_bytes():
                if len(data) + len(chunk) > 2_000_000:
                    raise UnreadablePage("page_too_large")
                data.extend(chunk)
            document = data.decode(response.encoding or "utf-8", errors="replace")
            if "text/plain" in media:
                paragraphs, title = document.splitlines(), original.host
            else:
                page = _ArticleText()
                page.feed(document)
                page.close()
                page.flush()
                paragraphs, title = page.passages, page.title
            excerpt = _excerpt(paragraphs, keywords + " " + unquote(parts.fragment))
            if not excerpt:
                raise UnreadablePage("no_readable_passage")
            return {"url": url, "title": " ".join(title.split())[:120] or original.host, "site": original.host,
                    "excerpt": excerpt, "origin": "page"}
    raise UnreadablePage("redirect_limit")


@tool
def read_web_sources(urls: list[str], keywords: str) -> dict:
    """Open up to three public HTTPS primary-source pages and return exact passages. Supply actual page URLs
    and specific search terms in the publisher's language for the claims you want to verify.
    You may open known publisher documentation directly or use URLs discovered by web_search."""
    sources = []
    for url in list(dict.fromkeys(urls))[:3]:
        try:
            sources.append(read_page(url, keywords[:512]))
        except (httpx.HTTPError, ValueError, OSError):
            continue
    return {"status": "ok" if sources else "empty", "sources": sources}
