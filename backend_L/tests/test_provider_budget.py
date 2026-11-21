"""Run the configured LangChain/OpenAI clients against in-memory HTTP transports."""
import asyncio
import json
import os
import socket
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

import httpx
from langgraph.graph import END, START, StateGraph
from openai import APIConnectionError

os.environ.setdefault("LLM_API_KEY", "offline")
os.environ.setdefault("LLM_BASE_URL", "http://localhost")

from config.model_limits import limits
from src.blog_agent.agent.agents import image_agent
from src.blog_agent.agent.state import AgentState
from src.blog_agent.clients import image_client, llm_client
from src.blog_agent.clients.provider_budget import (
    AsyncBudgetTransport, BudgetTransport, ProviderLimitError, current_budget, provider_run,
)


def completion(request):
    return httpx.Response(200, json={"id": "offline", "model": "offline", "object": "chat.completion",
                          "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"},
                                       "finish_reason": "stop"}]})


class ProviderBudgetTests(unittest.TestCase):
    def setUp(self):
        self.stack = self.enterContext(ExitStack())
        self.handler = Mock(side_effect=completion)
        self.http = self.enterContext(httpx.Client(transport=BudgetTransport(httpx.MockTransport(self.handler))))
        self.async_http = httpx.AsyncClient(transport=AsyncBudgetTransport(httpx.MockTransport(self.handler)))
        self.addCleanup(lambda: asyncio.run(self.async_http.aclose()))
        self.stack.enter_context(patch.object(llm_client, "http", self.http))
        self.stack.enter_context(patch.object(llm_client, "async_http", self.async_http))
        self.stack.enter_context(patch.object(limits, "enabled", True))
        self.stack.enter_context(patch.object(limits, "ai_images_enabled", True))
        self.stack.enter_context(patch.object(limits, "sdk_retries", 0))
        llm_client._get_chat_model_cached.cache_clear()
        self.addCleanup(llm_client._get_chat_model_cached.cache_clear)

    def test_real_sdk_and_graph_threads_share_one_stage_budget(self):
        model = llm_client.get_chat_model()
        graph = StateGraph(AgentState)
        graph.add_node("writer", lambda state: {"content": model.invoke("hello").content})
        graph.add_edge(START, "writer")
        graph.add_edge("writer", END)
        with patch.object(limits, "model_calls", 2), provider_run() as budget:
            self.assertEqual(graph.compile().invoke({"topic": "topic"})["content"], "ok")
            async def call():
                return await model.ainvoke("second")
            self.assertEqual(asyncio.run(call()).content, "ok")
            with self.assertRaises(APIConnectionError):
                model.invoke("over budget")
            self.assertEqual(budget.model_calls, 2)
        self.assertEqual(self.handler.call_count, 2)
        sent = json.loads(self.handler.call_args.args[0].content)
        self.assertEqual(sent.get("max_completion_tokens", sent.get("max_tokens")), limits.output_tokens)

    def test_wire_checks_cannot_be_overridden_at_invocation(self):
        model = llm_client.get_chat_model()
        with provider_run():
            for overrides in [{"max_tokens": limits.output_tokens + 1}, {"n": 4}, {"extra_body": {"enable_search": True}}]:
                with self.assertRaises(APIConnectionError):
                    model.bind(**overrides).invoke("hello")
            with patch.object(limits, "input_bytes", 100):
                with self.assertRaises(APIConnectionError):
                    model.invoke("hello" * 200)
        self.handler.assert_not_called()

    def test_network_retry_reserves_another_call(self):
        self.handler.side_effect = lambda request: httpx.Response(503, headers={"Retry-After-Ms": "1"})
        with patch.object(limits, "sdk_retries", 1), patch.object(limits, "model_calls", 1), provider_run():
            with self.assertRaises(APIConnectionError):
                llm_client.get_chat_model().invoke("test retry")
        self.handler.assert_called_once()

    def test_disabled_unscoped_and_expired_requests_send_nothing(self):
        def request():
            return self.http.get("https://offline.test/search", extensions={"provider_kind": "search"})
        with self.assertRaises(ProviderLimitError):
            request()
        with provider_run() as budget:
            with patch.object(limits, "enabled", False), self.assertRaises(ProviderLimitError):
                request()
            budget.deadline = 0
            with self.assertRaises(ProviderLimitError):
                request()
        self.handler.assert_not_called()

    def test_oversize_download_is_bounded(self):
        self.handler.side_effect = lambda request: httpx.Response(200, content=b"a" * 1025)
        address = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
        with patch("socket.getaddrinfo", return_value=address), patch.object(limits, "image_bytes", 1024), provider_run():
            with self.assertRaises(ProviderLimitError):
                self.http.get("https://images.pexels.com/test.jpg", extensions={"provider_kind": "image_download"})
        sent = self.handler.call_args.args[0]
        self.assertEqual(sent.url.host, "8.8.8.8")
        self.assertEqual(sent.extensions["sni_hostname"], "images.pexels.com")
        self.assertEqual(sent.headers["Host"], "images.pexels.com")

    def test_download_rejects_untrusted_private_redirected_and_non_image_responses(self):
        client = image_client.ImageClient()
        with tempfile.TemporaryDirectory() as directory, patch.object(image_client.settings, "image_save_dir", directory), patch.object(
            image_client, "http", self.http,
        ), patch("socket.getaddrinfo") as resolve, provider_run():
            for url in ["https://untrusted.test/photo", "http://images.pexels.com/a", "https://u:p@images.pexels.com/a",
                        "https://images.pexels.com:8443/a", "https://bucket.oss-cn-beijing-internal.aliyuncs.com/a"]:
                self.assertFalse(client.persist_image(url, "sample"))
            resolve.assert_not_called()
            url = "https://images.unsplash.com/photo"
            resolve.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
            self.assertFalse(client.persist_image(url, "sample"))
            self.handler.assert_not_called()
            resolve.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
            self.handler.side_effect = [httpx.Response(302, headers={"Location": "https://invalid.test"}),
                                        httpx.Response(200, content=b"text", headers={"Content-Type": "text/html"})]
            self.assertFalse(client.persist_image(url, "sample"))
            self.assertFalse(client.persist_image(url, "sample"))
            self.assertEqual(os.listdir(directory), [])
            self.assertEqual(self.handler.call_count, 2)

    def test_image_generation_and_polling_share_physical_tool_request_limit(self):
        client = image_client.ImageClient()
        self.handler.side_effect = lambda request: httpx.Response(200, json={"output": {"task_id": "demo"}})
        with patch.object(image_client, "http", self.http), patch.object(limits, "tool_requests", 1), provider_run():
            with self.assertRaises(ProviderLimitError):
                client._generate_image_wanx("offline", "draw a diagram", "offline")
        self.handler.assert_called_once()

    def test_parallel_images_have_same_budget_and_limit(self):
        client = image_client.ImageClient()
        def get(query, _source):
            current_budget().reserve("image_generation")
            return "/images/example.png"
        items = [{"index": i, "query_or_prompt": "a diagram"} for i in range(8)]
        with provider_run() as budget, patch.object(limits, "images", 2), patch.object(client, "fetch_image", get):
            result = client.fetch_all(items, "ai")
            self.assertEqual(result.count("/images/example.png"), 2)
            self.assertEqual(budget.image_generations, 2)
            with self.assertRaises(ProviderLimitError):
                current_budget().reserve("image_generation")
        with patch.object(limits, "ai_images_enabled", False), patch.object(image_agent, "chat") as model:
            content, urls = image_agent.process_images("text\n<!-- 配图：a diagram -->", "ai")
            self.assertFalse(urls)
            self.assertEqual(content.strip(), "text")
            model.assert_not_called()
