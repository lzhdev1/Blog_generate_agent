"""Count real outbound requests, including SDK retries, within one stage."""
import json
import ipaddress
import re
import socket
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic

import httpx

from config.model_limits import limits


class ProviderLimitError(RuntimeError):
    """A locally enforced limit stopped an outbound call."""


class RunBudget:
    def __init__(self):
        self.deadline = monotonic() + limits.stage_seconds
        self.model_calls = self.tool_calls = self.image_generations = 0
        self.lock = Lock()

    def remaining(self):
        left = self.deadline - monotonic()
        if left <= 0:
            raise ProviderLimitError("本阶段已达到执行时间上限。")
        return left

    def reserve(self, kind):
        if not limits.enabled:
            raise ProviderLimitError("管理员已关闭外部模型与工具调用。")
        with self.lock:
            self.remaining()
            if kind == "model":
                if self.model_calls >= limits.model_calls:
                    raise ProviderLimitError("本阶段模型调用已达到上限。")
                self.model_calls += 1
            else:
                if self.tool_calls >= limits.tool_requests:
                    raise ProviderLimitError("本阶段外部工具请求已达到上限。")
                if kind == "image_generation":
                    if not limits.ai_images_enabled or self.image_generations >= limits.images:
                        raise ProviderLimitError("AI 配图已关闭或达到本阶段张数上限。")
                    self.image_generations += 1
                self.tool_calls += 1


_budget = ContextVar("blog_provider_budget", default=None)


@contextmanager
def provider_run():
    """Nested subgraphs share a budget. Start an outer scope at each worker/CLI entry."""
    existing = _budget.get()
    if existing is not None:
        yield existing
        return
    budget = RunBudget()
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        _budget.reset(token)


def current_budget():
    budget = _budget.get()
    if budget is None:
        raise ProviderLimitError("外部调用缺少阶段执行上下文。")
    return budget


def _pin_image_source(request):
    url = request.url
    host = url.host
    public_oss = re.fullmatch(r"[a-z0-9-]+\.oss-[a-z0-9-]+\.aliyuncs\.com", host) and "-internal" not in host
    if url.scheme != "https" or url.userinfo or url.port not in (None, 443) or not (
        host in {"images.pexels.com", "images.unsplash.com", "plus.unsplash.com"} or public_oss
    ):
        raise ProviderLimitError("配图来源不在允许的供应商范围内。")
    try:
        addresses = [ipaddress.ip_address(addr[4][0]) for addr in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]
    except (OSError, ValueError) as error:
        raise ProviderLimitError("无法解析配图供应商地址。") from error
    if not addresses or any(not ip.is_global or ip.is_multicast for ip in addresses):
        raise ProviderLimitError("配图来源未解析到公共网络地址。")
    # Connect to the vetted IP while preserving certificate validation and signed URL Host.
    request.headers["Host"] = host
    request.headers["Connection"] = "close"
    request.extensions["sni_hostname"] = host
    request.url = url.copy_with(host=str(addresses[0]))


def _prepare(request):
    kind = request.extensions.get("provider_kind", "model")
    budget = current_budget()
    if len(request.content) > limits.input_bytes or len(str(request.url)) > 8192:
        raise ProviderLimitError("外部请求内容超过长度上限。")
    if kind == "model":
        payload = json.loads(request.content)
        caps = [payload[key] for key in ("max_tokens", "max_completion_tokens", "max_output_tokens") if key in payload]
        if not caps or any(type(n) is not int or not 0 < n <= limits.output_tokens for n in caps):
            raise ProviderLimitError("模型输出 token 上限缺失或超过配置。")
        if payload.get("n", 1) != 1:
            raise ProviderLimitError("一次模型调用只能生成一个结果。")
        if payload.get("enable_search") or any(t.get("type") != "function" for t in payload.get("tools", [])):
            raise ProviderLimitError("请关闭供应商托管工具，使用可计量的本地搜索工具。")
    budget.reserve(kind)
    if kind == "image_download":
        _pin_image_source(request)
    timeout = min(limits.request_seconds, budget.remaining())
    request.extensions["timeout"] = {
        key: min(value if value is not None else timeout, timeout)
        for key, value in request.extensions.get("timeout", dict.fromkeys(("read", "write", "connect", "pool"))).items()
    }
    request.headers["Accept-Encoding"] = "identity"
    byte_limit = (limits.image_bytes if kind == "image_download" else
                  3 * 1024 * 1024 if kind == "source_page" else
                  1024 * 1024 if kind == "model" else 256 * 1024)
    return budget, byte_limit


def _check_chunk(budget, size, cap):
    budget.remaining()
    if size > cap:
        raise ProviderLimitError("供应商响应超过大小上限。")


class _BoundedStream(httpx.SyncByteStream):
    def __init__(self, response, budget, cap):
        self.response, self.budget, self.cap = response, budget, cap

    def __iter__(self):
        size = 0
        for chunk in self.response.stream:
            size += len(chunk)
            _check_chunk(self.budget, size, self.cap)
            yield chunk

    def close(self):
        self.response.close()


class _BoundedAsyncStream(httpx.AsyncByteStream):
    def __init__(self, response, budget, cap):
        self.response, self.budget, self.cap = response, budget, cap

    async def __aiter__(self):
        size = 0
        async for chunk in self.response.stream:
            size += len(chunk)
            _check_chunk(self.budget, size, self.cap)
            yield chunk

    async def aclose(self):
        await self.response.aclose()


def _check_encoding(response):
    if response.headers.get("Content-Encoding", "identity").lower() != "identity":
        raise ProviderLimitError("供应商未遵循请求的响应编码，已停止读取。")


class BudgetTransport(httpx.BaseTransport):
    def __init__(self, inner=None):
        self.inner = inner if inner is not None else httpx.HTTPTransport()

    def handle_request(self, request):
        budget, cap = _prepare(request)
        response = self.inner.handle_request(request)
        try:
            _check_encoding(response)
            return httpx.Response(response.status_code, headers=response.headers, extensions=response.extensions,
                                  stream=_BoundedStream(response, budget, cap))
        except BaseException:
            response.close()
            raise

    def close(self):
        self.inner.close()


class AsyncBudgetTransport(httpx.AsyncBaseTransport):
    def __init__(self, inner=None):
        self.inner = inner if inner is not None else httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        budget, cap = _prepare(request)
        response = await self.inner.handle_async_request(request)
        try:
            _check_encoding(response)
            return httpx.Response(response.status_code, headers=response.headers, extensions=response.extensions,
                                  stream=_BoundedAsyncStream(response, budget, cap))
        except BaseException:
            await response.aclose()
            raise

    async def aclose(self):
        await self.inner.aclose()


# LangChain, the OpenAI SDK, web search and image providers use the same wire-level guard.
http = httpx.Client(transport=BudgetTransport(), follow_redirects=False)
async_http = httpx.AsyncClient(transport=AsyncBudgetTransport(), follow_redirects=False)
