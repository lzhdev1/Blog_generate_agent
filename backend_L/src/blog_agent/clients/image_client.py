"""
图片客户端：搜图（Pexels / Unsplash）+ AI 生图（百炼）+ 本地持久化

职责边界（企业分层）：
- 本模块只做纯 I/O 能力：调图片 API、选图、下载持久化，不含任何 LLM 逻辑；
- LLM 分析配图位置、生成搜图关键词 / AI 生图 prompt，属于 image 子图节点
  （nodes/react_model + image_prompts.py），不在这里。

对外能力：
- search(query)          按关键词搜图（Pexels 优先，Unsplash 兜底）
- select_best_image()    候选按关键词相关性排序（确定性算法）
- generate_image(prompt) AI 生图（qwen-image 新接口 / wanx 旧接口自动路由）
- persist_image(url)     下载远程图到本地持久化（解决 OSS 临时链接过期）
- fetch_image(...)       统一入口：按配图方式取一张图
- fetch_all(...)         并发获取多张图（缩短配图总耗时）
"""
import logging
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from typing import Dict, List, Optional

import httpx

from config.model_limits import limits
from config.settings import settings
from src.blog_agent.clients.provider_budget import ProviderLimitError, current_budget, http

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                     "image/webp": ".webp", "image/avif": ".avif"}
# 搜索 API 超时（秒）
_SEARCH_TIMEOUT = 10
# 生图/下载超时（秒）
_GEN_TIMEOUT = 120


class ImageClient:
    """配图纯 I/O 客户端（进程级单例使用）"""

    # ============================================================
    # 1. 搜图（Pexels / Unsplash）
    # ============================================================

    def search_pexels(self, query: str, limit: int = 5) -> List[Dict]:
        """
        调用 Pexels API 搜索图片。
        返回：[{"url", "title", "alt"}, ...]，失败或未配置 Key 返回 []
        """
        api_key = settings.pexels_api_key
        if not api_key:
            logger.warning("未配置 pexels_api_key，跳过 Pexels 搜索")
            return []
        try:
            resp = http.get(
                "https://api.pexels.com/v1/search",
                params={"query": query[:512], "per_page": min(5, limit), "orientation": "landscape"},
                headers={"Authorization": api_key},
                timeout=_SEARCH_TIMEOUT,
                extensions={"provider_kind": "image_search"},
            )
            if resp.status_code == 200:
                candidates = []
                for photo in resp.json().get("photos", [])[:limit]:
                    sizes = photo.get("src") if isinstance(photo, dict) else None
                    if isinstance(sizes, dict):
                        url = sizes.get("large") or sizes.get("medium") or sizes.get("original")
                        if isinstance(url, str) and url:
                            candidates.append({"url": url, "title": "", "alt": photo.get("alt") or ""})
                return candidates
            logger.warning("Pexels 搜索失败: HTTP %s", resp.status_code)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Pexels 搜索响应无效: %s", type(e).__name__)
        return []

    def search_unsplash(self, query: str, limit: int = 5) -> List[Dict]:
        """
        调用 Unsplash API 搜索图片（Pexels 无结果时的兜底）。
        返回：[{"url", "title", "alt"}, ...]，失败或未配置 Key 返回 []
        """
        api_key = settings.unsplash_access_key
        if not api_key:
            logger.warning("未配置 unsplash_access_key，跳过 Unsplash 搜索")
            return []
        try:
            resp = http.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query[:512], "per_page": min(5, limit), "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {api_key}"},
                timeout=_SEARCH_TIMEOUT,
                extensions={"provider_kind": "image_search"},
            )
            if resp.status_code == 200:
                candidates = []
                for photo in resp.json().get("results", [])[:limit]:
                    sizes = photo.get("urls") if isinstance(photo, dict) else None
                    if isinstance(sizes, dict):
                        url = sizes.get("regular") or sizes.get("small")
                        if isinstance(url, str) and url:
                            candidates.append({"url": url, "title": photo.get("description") or "",
                                               "alt": photo.get("alt_description") or ""})
                return candidates
            logger.warning("Unsplash 搜索失败: HTTP %s", resp.status_code)
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as e:
            logger.warning("Unsplash 搜索响应无效: %s", type(e).__name__)
        return []

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """按关键词搜图：Pexels 优先，无结果时 Unsplash 兜底"""
        candidates = self.search_pexels(query, limit)
        if not candidates:
            candidates = self.search_unsplash(query, limit)
        return candidates

    # ============================================================
    # 2. 候选图相关性排序（确定性算法，无 LLM）
    # ============================================================

    @staticmethod
    def select_best_image(candidates: List[Dict], query: str) -> Optional[str]:
        """
        从候选中选择与搜索关键词最相关的一张。
        以英文关键词和中文连续双字匹配图片的 alt/title；
        缺少可核对的关键词匹配时跳过配图。
        """
        def terms(text: str) -> set[str]:
            words = set(re.findall(r"[a-z0-9]+", text.lower()))
            words.difference_update({"a", "an", "the", "and", "in", "on", "of", "at", "for", "with", "to"})
            for word in re.findall(r"[\u3400-\u9fff]{2,}", text):
                words.update(word[i:i + 2] for i in range(len(word) - 1))
            return words

        query_words = terms(query)
        if not query_words:
            return None

        best_url = None
        best_score = 0.0
        for c in candidates:
            text = f"{c.get('alt', '')} {c.get('title', '')}".lower()
            text_words = terms(text)
            if not text_words:
                continue
            overlap = len(query_words & text_words)
            score = overlap / len(query_words)
            if score > best_score:
                best_score = score
                best_url = c["url"]
        return best_url

    # ============================================================
    # 3. AI 生图（百炼）
    # ============================================================

    def generate_image(self, prompt: str) -> Optional[str]:
        """
        调用百炼生成图片，返回图片 URL，失败返回 None。
        按模型自动路由：
        - qwen-image*  -> 多模态对话新接口（同步）
        - 其他（wanx*）-> text2image 旧接口（异步轮询）
        """
        if not limits.ai_images_enabled or not limits.images or not prompt or len(prompt) > 4096:
            return None
        api_key = settings.image_api_key or settings.llm_api_key
        model = settings.image_gen_model
        if model.startswith("qwen-image"):
            return self._generate_image_qwen(model, prompt, api_key)
        return self._generate_image_wanx(model, prompt, api_key)

    def _generate_image_qwen(self, model: str, prompt: str, api_key: str) -> Optional[str]:
        """qwen-image 新接口：多模态对话，同步返回图片 URL"""
        workspace_id = settings.dashscope_workspace_id
        if not workspace_id:
            logger.error("qwen-image 需要配置 dashscope_workspace_id（业务空间ID）")
            return None
        try:
            url = (
                f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/"
                f"aigc/multimodal-generation/generation"
            )
            data = {
                "model": model,
                "input": {
                    "messages": [{"role": "user", "content": [{"text": prompt}]}]
                },
                "parameters": {"prompt_extend": True, "size": "1024*1024", "n": 1},
            }
            resp = http.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=data,
                timeout=_GEN_TIMEOUT,
                extensions={"provider_kind": "image_generation"},
            )
            if resp.status_code == 200:
                result = resp.json()
                choices = result.get("output", {}).get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", [])
                    if content:
                        image_url = content[0].get("image")
                        if image_url:
                            return image_url
                logger.error("qwen-image 返回格式异常: %s", result)
            else:
                logger.error("qwen-image 调用失败: HTTP %s %s", resp.status_code, resp.text[:200])
        except httpx.HTTPError as e:
            logger.error("qwen-image 生成异常: %s", e)
        return None

    def _generate_image_wanx(self, model: str, prompt: str, api_key: str) -> Optional[str]:
        """通义万相旧接口：异步提交任务并轮询结果"""
        try:
            resp = http.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "X-DashScope-Async": "enable",
                },
                json={
                    "model": model,
                    "input": {"prompt": prompt},
                    "parameters": {"size": "1024*1024", "n": 1},
                },
                timeout=30,
                extensions={"provider_kind": "image_generation"},
            )
            if resp.status_code == 200:
                task_id = resp.json().get("output", {}).get("task_id")
                if task_id:
                    return self._poll_dashscope_task(task_id, api_key)
            logger.warning("wanx 提交失败: HTTP %s", resp.status_code)
        except httpx.HTTPError as e:
            logger.error("wanx 生成异常: %s", e)
        return None

    @staticmethod
    def _poll_dashscope_task(task_id: str, api_key: str, max_retries: int = 30) -> Optional[str]:
        """轮询百炼异步任务结果（每 2s 一次，最多 60s）"""
        import time

        url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {api_key}"}
        for _ in range(min(30, max_retries)):
            try:
                resp = http.get(url, headers=headers, timeout=10, extensions={"provider_kind": "image_poll"})
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("output", {}).get("task_status")
                    if status == "SUCCEEDED":
                        results = data.get("output", {}).get("results", [])
                        if results:
                            return results[0].get("url")
                    elif status == "FAILED":
                        logger.warning("wanx 任务失败: %s", task_id)
                        return None
            except httpx.HTTPError:
                pass
            time.sleep(min(2, current_budget().remaining()))
        logger.warning("wanx 任务轮询超时: %s", task_id)
        return None

    # ============================================================
    # 4. 本地持久化（解决 AI 生图 OSS 临时链接过期）
    # ============================================================

    def persist_image(self, url: str, filename: str) -> str:
        """
        把远程图片下载到本地持久化，返回本地 URL（/images/<filename>）。
        - 已是本地 URL（/images/ 开头）直接返回；
        - 来源、网络或格式校验失败时略去图片，保留已审核的正文。
        """
        if not url:
            return ""
        if url.startswith("/images/"):
            return url if re.fullmatch(r"/images/[\w-]+\.(?:jpe?g|png|webp|gif|avif)", url, re.I) else ""
        if not re.fullmatch(r"[\w-]{1,128}", filename):
            return ""
        temp_path = None
        try:
            save_dir = settings.image_save_dir
            os.makedirs(save_dir, exist_ok=True)

            resp = http.get(url, timeout=30, extensions={"provider_kind": "image_download"})
            if resp.status_code != 200:
                logger.warning("图片下载失败 HTTP %s", resp.status_code)
                return ""

            media_type = resp.headers.get("content-type", "").partition(";")[0].lower()
            ext = _IMAGE_EXTENSIONS.get(media_type)
            if not resp.content or not ext:
                return ""
            save_path = os.path.join(save_dir, f"{filename}{ext}")
            temp_path = Path(f"{save_path}.{uuid.uuid4().hex}.part")
            temp_path.write_bytes(resp.content)
            os.replace(temp_path, save_path)

            logger.info("图片已持久化: %s", save_path)
            return f"/images/{filename}{ext}"
        except (httpx.HTTPError, httpx.InvalidURL, ProviderLimitError, OSError) as error:
            logger.warning("配图下载已略过：%s", type(error).__name__)
            return ""
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    # ============================================================
    # 5. 统一入口
    # ============================================================

    @staticmethod
    def _is_valid_query(text: str) -> bool:
        """基础防御：空串或过短的输入直接拒绝，避免浪费 API 调用"""
        stripped = (text or "").strip()
        return len(stripped) >= 3

    def fetch_image(self, query_or_prompt: str, image_source: str) -> Optional[str]:
        """
        根据配图方式获取一张图片（调用方已生成好关键词/prompt，此处不做文字转换）。
        - image_source="api"：直接以关键词搜图（Pexels → Unsplash → 相关性选图）
        - image_source="ai" ：直接以 prompt 调 AI 生图
        返回图片 URL，失败返回 None。
        """
        text = (query_or_prompt or "").strip()
        if not self._is_valid_query(text):
            logger.warning("配图关键词/prompt 无效（过短），跳过: %r", text[:30])
            return None

        if image_source == "api":
            candidates = self.search(text)
            return self.select_best_image(candidates, text) if candidates else None
        return self.generate_image(text) if image_source == "ai" else None

    def fetch_all(
        self,
        items: List[Dict],
        image_source: str,
        max_workers: int = 4,
        prefix: str = "img",
    ) -> List[Optional[str]]:
        """
        并发获取多张配图并持久化到本地。
        items: [{"index": int, "query_or_prompt": str}, ...]（顺序与正文标记一一对应）
        返回与 items 等长的 URL 列表（失败项为 None），文件名带唯一 run_id，
        保证每次运行生成的图片不复用历史图片。
        """
        run_id = uuid.uuid4().hex[:8]
        results: List[Optional[str]] = [None] * len(items)

        def _fetch(item: Dict, position: int) -> None:
            try:
                url = self.fetch_image(item.get("query_or_prompt", ""), image_source)
                if url:
                    results[position] = self.persist_image(
                        url, f"{prefix}_{run_id}_{item.get('index', position) + 1}"
                    )
            except Exception as error:
                # Each worker owns one optional illustration. Preserve any successful siblings.
                logger.warning("已跳过第%d处配图：%s", position + 1, type(error).__name__)

        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 4))) as pool:
            futures = [
                pool.submit(copy_context().run, _fetch, item, position)
                for position, item in enumerate(items[:limits.images])
            ]
            for f in futures:
                f.result()  # 内部已吞异常，result() 不会抛

        return results


# 全局单例：整个项目共用这一个客户端实例（复用同一 HTTP Session）
image_client = ImageClient()
