import re
import json
import os
import requests
from typing import List, Dict, Optional, Tuple

from src.blog_agent.agent.agents.base_agent import BaseAgent
from config.settings import settings

# 全局 HTTP Session：复用 TCP 连接，避免每次搜索/下载都新建连接（显著减少握手开销）
_image_http = requests.Session()


class ImageAgent(BaseAgent):
    """配图 Agent：负责生成配图提示词、搜索/生成图片、插入正文"""

    name = "image"
    role = "配图设计师"
    system_prompt = """你是一个专业的配图设计师，擅长：
1. 根据文章内容分析哪些位置需要配图
2. 生成精准的图片搜索关键词或AI绘画提示词
3. 确保图片风格和文章内容匹配"""
    model_config_key = "llm_model_image"  # 配图agent专用模型，用便宜的模型生成提示词即可

    # 无效占位描述（模型照抄格式示例时产生），命中则跳过搜索/生图，直接走降级
    INVALID_IMAGE_MARKERS = {
        "搜索关键词", "具体搜索关键词", "图片搜索关键词", "配图关键词",
        "画面描述", "配图描述", "图片描述", "配图位置和搜索关键词",
        "关键词", "描述", "search keywords", "image description",
    }

    # ============================================================
    # 1. 从大纲中提取配图位置
    # ============================================================

    def extract_image_positions(self, outline: str) -> List[Dict]:
        """
        从大纲中提取配图位置和要求
        大纲中的配图标记格式：<!-- 配图：描述 -->
        返回：[{"position": "章节标题", "description": "配图描述"}, ...]
        """
        positions = []
        # 匹配 <!-- 配图：描述 --> 格式
        pattern = r'<!--\s*配图[：:]\s*(.+?)\s*-->'
        matches = list(re.finditer(pattern, outline))

        for i, match in enumerate(matches):
            description = match.group(1).strip()
            # 找到这个注释前面最近的标题，作为位置标识
            before_text = outline[:match.start()]
            title_matches = list(re.finditer(r'^#{1,4}\s+(.+)$', before_text, re.MULTILINE))
            position = title_matches[-1].group(1).strip() if title_matches else f"第{i+1}个配图位置"
            positions.append({
                "index": i,
                "position": position,
                "description": description,
            })

        return positions

    # ============================================================
    # 2. 生成配图提示词
    # ============================================================

    def generate_image_prompt(self, description: str, image_source: str = "ai") -> str:
        """
        根据配图描述生成图片提示词
        image_source: "api"（搜索关键词）或 "ai"（AI绘画提示词）
        """
        if image_source == "api":
            # 生成搜索关键词
            prompt = f"""请将以下配图描述转换成英文图片搜索关键词，用空格分隔，不要超过10个单词：
配图描述：{description}
直接输出关键词，不要其他解释。"""
            return self.chat(prompt, temperature=0.3)
        else:
            # 生成AI绘画提示词
            prompt = f"""请将以下配图描述转换成详细的AI绘画提示词（英文），包含：
1. 主体内容
2. 风格（科技感/扁平插画/写实等）
3. 色调
4. 构图

配图描述：{description}
直接输出提示词，不要其他解释。"""
            return self.chat(prompt, temperature=0.7)

    # ============================================================
    # 3. 搜索图片（图片网站API）
    # ============================================================

    def generate_query_variants(self, description: str, max_variants: int = 3) -> List[str]:
        """
        搜索失败时，让 LLM 基于原关键词生成【保留核心语义】的搜索关键词变体
        通过同义词替换、补充场景/氛围限定词变体化，不改变主题方向
        返回：变体关键词列表
        """
        prompt = f"""以下英文图片搜索关键词在图片库搜不到合适的图。请生成 {max_variants} 个新的英文搜索关键词变体，要求：
1. 必须保留原关键词的核心主题和主体，【禁止】改变语义方向（如"代码编辑器"不能变成"风景""办公桌"）
2. 通过同义词替换、补充场景/氛围限定词的方式变体化
3. 每个关键词5-8个单词，空格分隔，可直接用于Pexels/Unsplash搜索
4. 一行一个，直接输出，不要解释、不要编号

原关键词：{description}

{max_variants}个变体："""
        try:
            raw = self.chat(prompt, temperature=0.5)
            variants = []
            for line in raw.split("\n"):
                line = line.strip()
                line = re.sub(r'^\d+[.、)）\s]+', '', line)   # 去行首编号
                line = line.strip('-').strip('*').strip('.').strip()
                if len(line) >= 3 and line not in variants:
                    variants.append(line)
            return variants[:max_variants]
        except Exception as e:
            print(f"[image] 生成关键词变体失败: {e}")
            return []

    def search_image_with_retry(
        self,
        description: str,
        max_retries: int = 2,
        use_direct_query: bool = False,
    ) -> Tuple[Optional[str], bool]:
        """
        带重试的图片搜索
        - use_direct_query=True：直接把 description 作为搜索关键词
          （调用方已通过 analyze_image_needs 生成好关键词，不再二次转换，保证语义不变）
        - 首次失败后，让 LLM 基于原语义生成关键词变体（保留核心语义），逐个重试
        返回：(图片URL或None, 是否搜索成功)
        """
        # 首次：直接用关键词（或让 LLM 从描述转换）
        query = description if use_direct_query else self.generate_image_prompt(description, "api")
        candidates = self.search_image_pexels(query)
        if not candidates:
            candidates = self.search_image_unsplash(query)
        image_url = self.select_best_image(candidates, query) if candidates else None
        if image_url:
            return image_url, True

        # 重试：生成保留核心语义的关键词变体，逐个搜索
        variants = self.generate_query_variants(description)
        for attempt, variant in enumerate(variants[:max_retries]):
            print(f"[image] 配图搜索失败（第{attempt + 1}次），使用语义变体重试: {variant}")
            candidates = self.search_image_pexels(variant)
            if not candidates:
                candidates = self.search_image_unsplash(variant)
            image_url = self.select_best_image(candidates, variant) if candidates else None
            if image_url:
                return image_url, True

        return None, False

    def select_best_image(self, candidates: List[Dict], query: str) -> Optional[str]:
        """
        从候选图片中选择与搜索关键词最相关的一张
        相关性评分：query 中的词与图片 alt/title 文本的词重合度（precision-like）
        无候选返回 None；无法评分时回退第一张
        """
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]["url"]

        query_words = set(re.findall(r"[a-z0-9]+", query.lower()))
        if not query_words:
            return candidates[0]["url"]

        best = candidates[0]
        best_score = -1.0
        for c in candidates:
            text = f"{c.get('alt', '')} {c.get('title', '')}".lower()
            text_words = set(re.findall(r"[a-z0-9]+", text))
            if not text_words:
                continue
            overlap = len(query_words & text_words)
            score = overlap / len(query_words)
            if score > best_score:
                best_score = score
                best = c

        return best["url"]

    def replace_image_with_text(self, content: str, position: str, description: str) -> str:
        """
        配图失败时，把配图位置改成纯文本过渡句
        在对应章节标题后插入一段引导文字，代替图片
        """
        prompt = f"""文章中有一个位置原本计划配图，但搜不到合适的图片。请写一句简短的过渡句（不超过50字），代替图片，自然地引出下文内容。

章节：{position}
原配图要求：{description}

直接输出过渡句，不要其他解释。"""
        transition = self.chat(prompt, temperature=0.5)

        # 在对应章节标题后插入过渡句
        escaped_position = re.escape(position)
        pattern = f'(^#{{1,4}}\\s+{escaped_position}\\s*$)'
        replacement = f'\\1\n\n{transition}\n'
        new_content = re.sub(pattern, replacement, content, count=1, flags=re.MULTILINE)

        if new_content == content:
            # 找不到标题，在末尾追加
            new_content = content + f'\n\n{transition}\n'

        return new_content

    def search_image_unsplash(self, query: str, limit: int = 5) -> List[Dict]:
        """
        调用 Unsplash API 搜索图片，返回候选列表（含描述信息，供相关性排序）
        需要配置 UNSPLASH_ACCESS_KEY
        返回：[{"url": ..., "title": ..., "alt": ...}, ...]，失败返回 []
        """
        api_key = getattr(settings, "unsplash_access_key", None)
        if not api_key:
            return []

        try:
            url = "https://api.unsplash.com/search/photos"
            params = {
                "query": query,
                "per_page": limit,
                "orientation": "landscape",
            }
            headers = {"Authorization": f"Client-ID {api_key}"}
            resp = _image_http.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                candidates = []
                for r in data.get("results", [])[:limit]:
                    candidates.append({
                        "url": r["urls"]["regular"],
                        "title": r.get("description") or "",
                        "alt": r.get("alt_description") or "",
                    })
                return candidates
        except Exception as e:
            print(f"Unsplash搜索失败: {e}")
        return []

    def search_image_pexels(self, query: str, limit: int = 5) -> List[Dict]:
        """
        调用 Pexels API 搜索图片，返回候选列表（含描述信息，供相关性排序）
        需要配置 PEXELS_API_KEY
        返回：[{"url": ..., "title": ..., "alt": ...}, ...]，失败返回 []
        """
        api_key = getattr(settings, "pexels_api_key", None)
        if not api_key:
            return []

        try:
            url = "https://api.pexels.com/v1/search"
            params = {
                "query": query,
                "per_page": limit,
                "orientation": "landscape",
            }
            headers = {"Authorization": api_key}
            resp = _image_http.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                candidates = []
                for p in data.get("photos", [])[:limit]:
                    candidates.append({
                        "url": p["src"]["large"],
                        "title": "",
                        "alt": p.get("alt") or "",
                    })
                return candidates
        except Exception as e:
            print(f"Pexels搜索失败: {e}")
        return []

    # ============================================================
    # 4. AI生成图片（百炼通义万相）
    # ============================================================

    def generate_image_dashscope(self, prompt: str) -> Optional[str]:
        """
        调用百炼生成图片
        支持两种模型：
        - qwen-image-3.0 / qwen-image-3.0-pro：新的多模态对话接口（同步调用）
        - wanx2.1-t2i-turbo 等旧模型：旧的 text2image 接口（异步轮询）
        API Key 优先用 image_api_key，没有则用 llm_api_key
        返回图片URL，失败返回None
        """
        api_key = getattr(settings, "image_api_key", None) or settings.llm_api_key
        model = getattr(settings, "image_gen_model", "wanx2.1-t2i-turbo")

        # qwen-image 系列用新接口
        if model.startswith("qwen-image"):
            return self._generate_image_qwen(model, prompt, api_key)
        # 旧模型用 wanx 接口
        else:
            return self._generate_image_wanx(model, prompt, api_key)

    def _generate_image_qwen(self, model: str, prompt: str, api_key: str) -> Optional[str]:
        """
        qwen-image-3.0 新接口：多模态对话，同步调用
        需要 dashscope_workspace_id
        """
        workspace_id = getattr(settings, "dashscope_workspace_id", None)
        if not workspace_id:
            print("qwen-image-3.0 需要配置 dashscope_workspace_id（业务空间ID）")
            return None

        try:
            url = f"https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            data = {
                "model": model,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [{"text": prompt}]
                        }
                    ]
                },
                "parameters": {
                    "prompt_extend": True,
                    "size": "1024*1024",
                    "n": 1,
                }
            }
            resp = _image_http.post(url, headers=headers, json=data, timeout=120)
            if resp.status_code == 200:
                result = resp.json()
                # 新接口返回格式：output.choices[0].message.content[0].image
                choices = result.get("output", {}).get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", [])
                    if content:
                        image_url = content[0].get("image")
                        if image_url:
                            return image_url
                print(f"qwen-image 返回格式异常: {result}")
            else:
                print(f"qwen-image 调用失败: {resp.status_code} {resp.text}")
        except Exception as e:
            print(f"qwen-image 生成失败: {e}")
        return None

    def _generate_image_wanx(self, model: str, prompt: str, api_key: str) -> Optional[str]:
        """
        旧的通义万相接口：异步调用，轮询任务结果
        """
        try:
            url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            }
            data = {
                "model": model,
                "input": {"prompt": prompt},
                "parameters": {"size": "1024*1024", "n": 1},
            }
            resp = _image_http.post(url, headers=headers, json=data, timeout=30)
            if resp.status_code == 200:
                result = resp.json()
                task_id = result.get("output", {}).get("task_id")
                if task_id:
                    return self._poll_dashscope_task(task_id, api_key)
        except Exception as e:
            print(f"百炼图片生成失败: {e}")
        return None

    def _poll_dashscope_task(self, task_id: str, api_key: str, max_retries: int = 30) -> Optional[str]:
        """轮询百炼图片生成任务结果"""
        import time
        url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {api_key}"}

        for _ in range(max_retries):
            try:
                resp = _image_http.get(url, headers=headers, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("output", {}).get("task_status")
                    if status == "SUCCEEDED":
                        results = data.get("output", {}).get("results", [])
                        if results:
                            return results[0].get("url")
                    elif status == "FAILED":
                        return None
            except Exception:
                pass
            time.sleep(2)
        return None

    # ============================================================
    # 5. 统一配图入口
    # ============================================================

    def get_image(self, description: str, image_source: str) -> Optional[str]:
        """
        根据配图描述和配图方式获取图片
        image_source: "api"（搜索图片）或 "ai"（AI生成）
        返回图片URL，失败返回None
        """
        # 防御：无效占位描述直接判失败，避免浪费搜索/生图调用
        stripped = (description or "").strip()
        if not stripped or stripped in self.INVALID_IMAGE_MARKERS or len(stripped) < 3:
            print(f"[image] 配图描述无效（占位词或过短），跳过: {stripped!r}")
            return None

        if image_source == "api":
            # 搜索图片：带重试，失败时优化描述再搜
            image_url, success = self.search_image_with_retry(stripped, max_retries=2)
            return image_url
        else:
            # AI生成
            prompt = self.generate_image_prompt(stripped, "ai")
            return self.generate_image_dashscope(prompt)

    def persist_image(self, url: str, filename: str) -> str:
        """
        把远程图片下载到本地持久化，返回本地URL（/images/<filename>）
        解决 AI 生图临时链接（OSS）过期失效的问题
        - 已是本地 URL（/images/ 开头）直接返回
        - 下载失败回退返回原 URL（不阻塞流程）
        """
        if not url or url.startswith("/images/"):
            return url

        try:
            import os
            save_dir = getattr(settings, "image_save_dir", "/app/data/images")
            os.makedirs(save_dir, exist_ok=True)

            # 从 URL 提取扩展名（.jpg/.png/.jpeg/.webp），没有则按内容判断
            path = url.split("?", 1)[0]
            ext = os.path.splitext(path)[1].lower()
            if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
                ext = ".jpg"

            save_path = os.path.join(save_dir, f"{filename}{ext}")

            # 已存在则直接返回（幂等）
            if os.path.exists(save_path):
                return f"/images/{filename}{ext}"

            resp = _image_http.get(url, timeout=30, stream=True)
            if resp.status_code != 200:
                print(f"[image] 图片下载失败 HTTP {resp.status_code}: {url[:80]}")
                return url

            with open(save_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            # 校验非空
            if os.path.getsize(save_path) == 0:
                os.remove(save_path)
                return url

            print(f"[image] 图片已持久化: {save_path}")
            return f"/images/{filename}{ext}"
        except Exception as e:
            print(f"[image] 图片持久化失败，回退原URL: {e}")
            return url

    # ============================================================
    # 6. 把图片插入正文
    # ============================================================

    def _normalize_title(self, title: str) -> str:
        """标准化标题，用于模糊匹配：去掉序号、标点、空格"""
        import re
        # 去掉开头的序号（如 "1. "、"3、"、"一、"）
        t = re.sub(r'^[\d一二三四五六七八九十]+[.、\)\s]+', '', title)
        # 去掉所有标点和空格
        t = re.sub(r'[^\w\u4e00-\u9fff]', '', t)
        return t.strip()

    def extract_image_markers_from_content(self, content: str) -> List[Dict]:
        """
        从正文中提取配图标记 <!-- 配图：描述 -->
        返回：[{"index": int, "description": str, "start": int, "end": int}, ...]
        """
        markers = []
        pattern = r'<!--\s*配图[：:]\s*(.+?)\s*-->'
        for i, match in enumerate(re.finditer(pattern, content)):
            markers.append({
                "index": i,
                "description": match.group(1).strip(),
                "start": match.start(),
                "end": match.end(),
            })
        return markers

    def insert_images_by_markers(
        self,
        content: str,
        image_markers: List[Dict],
        image_urls: List[Optional[str]],
    ) -> Tuple[str, List[str]]:
        """
        直接把正文中的配图标记替换成图片markdown
        按标记位置从后往前替换，避免位置偏移
        返回：(替换后的正文, 成功插入的图片URL列表)
        """
        result = content
        inserted_urls = []

        # 从后往前替换，避免位置偏移
        for i in range(len(image_markers) - 1, -1, -1):
            marker = image_markers[i]
            if i >= len(image_urls) or not image_urls[i]:
                # 配图失败，删除标记
                result = result[:marker["start"]] + result[marker["end"]:]
                continue

            image_url = image_urls[i]
            alt_text = f"配图{i+1}"
            replacement = f'![{alt_text}]({image_url})'
            result = result[:marker["start"]] + replacement + result[marker["end"]:]
            inserted_urls.append(image_url)

        # inserted_urls 是倒序的，反转回来
        inserted_urls.reverse()
        return result, inserted_urls

    def insert_images_to_content(
        self,
        content: str,
        image_positions: List[Dict],
        image_urls: List[Optional[str]],
    ) -> Tuple[str, List[str]]:
        """
        [已废弃] 用标题匹配的方式插入图片
        推荐使用 insert_images_by_markers 直接替换配图标记
        """
        result = content
        inserted_urls = []

        content_headers = []
        for match in re.finditer(r'^(#{1,4})\s+(.+)$', content, re.MULTILINE):
            content_headers.append({
                'full': match.group(0),
                'title': match.group(2).strip(),
                'normalized': self._normalize_title(match.group(2)),
                'start': match.start(),
                'end': match.end(),
            })

        for i, pos in enumerate(image_positions):
            if i >= len(image_urls) or not image_urls[i]:
                continue

            image_url = image_urls[i]
            alt_text = f"配图{i+1}"
            target_title = pos["position"]
            target_normalized = self._normalize_title(target_title)

            matched_header = None
            for h in content_headers:
                if h['title'] == target_title:
                    matched_header = h
                    break
            if not matched_header:
                for h in content_headers:
                    if h['normalized'] == target_normalized:
                        matched_header = h
                        break
            if not matched_header:
                for h in content_headers:
                    if target_normalized and (target_normalized in h['normalized'] or h['normalized'] in target_normalized):
                        matched_header = h
                        break

            if matched_header:
                insert_pos = matched_header['end']
                result = result[:insert_pos] + f'\n\n![{alt_text}]({image_url})\n' + result[insert_pos:]
                inserted_urls.append(image_url)
                offset = len(f'\n\n![{alt_text}]({image_url})\n')
                for h in content_headers:
                    if h['start'] > insert_pos:
                        h['start'] += offset
                        h['end'] += offset
            else:
                result += f'\n\n![{alt_text}]({image_url})\n'
                inserted_urls.append(image_url)

        return result, inserted_urls

    # ============================================================
    # 7. 配图上下文分析（优化版）
    # ============================================================

    def extract_markers_with_context(self, content: str, context_chars: int = 200) -> List[Dict]:
        """
        从正文中提取配图标记，并附带每个标记的上下文（前后各 context_chars 字）
        返回：[{"index": int, "description": str, "context_before": str, "context_after": str, "position_title": str, "start": int, "end": int}, ...]
        """
        markers = []
        pattern = r'<!--\s*配图[：:]\s*(.+?)\s*-->'
        for i, match in enumerate(re.finditer(pattern, content)):
            description = match.group(1).strip()
            start = match.start()
            end = match.end()

            # 提取上下文
            context_before = content[max(0, start - context_chars):start].strip()
            context_after = content[end:min(len(content), end + context_chars)].strip()

            # 找到这个注释前面最近的标题，作为位置标识
            before_text = content[:start]
            title_matches = list(re.finditer(r'^#{1,4}\s+(.+)$', before_text, re.MULTILINE))
            position_title = title_matches[-1].group(1).strip() if title_matches else f"第{i+1}个配图位置"

            markers.append({
                "index": i,
                "description": description,
                "context_before": context_before,
                "context_after": context_after,
                "position_title": position_title,
                "start": start,
                "end": end,
            })

        return markers

    def analyze_image_needs(self, markers_with_context: List[Dict], image_source: str) -> List[Dict]:
        """
        LLM 深度分析每个配图位置的上下文，生成专业的搜图关键词或AI生图prompt
        image_source: "api"（搜图）或 "ai"（AI生图）
        返回：[{"index": int, "query_or_prompt": str, "description_cn": str}, ...]
        """
        if not markers_with_context:
            return []

        results = []

        # 逐个分析（单个分析更精准，避免批量分析时上下文混淆）
        for marker in markers_with_context:
            idx = marker["index"]
            description = marker["description"]
            context_before = marker["context_before"]
            context_after = marker["context_after"]
            position_title = marker["position_title"]

            # 无效占位描述直接跳过
            stripped = (description or "").strip()
            if not stripped or stripped in self.INVALID_IMAGE_MARKERS or len(stripped) < 3:
                print(f"[image] 配图位置{idx+1}描述无效（占位词或过短），跳过分析: {stripped!r}")
                results.append({"index": idx, "query_or_prompt": "", "description_cn": ""})
                continue

            if image_source == "api":
                # 搜图模式：生成简洁专业的英文搜索关键词 + 中文描述
                prompt = f"""你是一个专业的图片编辑。请分析以下文章中某个配图位置的上下文，生成精准的图片搜索关键词。

【配图位置的章节标题】：{position_title}
【配图位置的前文】：{context_before[:300]}
【配图位置的后文】：{context_after[:300]}
【原配图说明】：{description}

请输出：
1. 搜图关键词（英文，5-8个单词，空格分隔，简洁专业，可直接用于Pexels/Unsplash等图片库搜索）
2. 搜图描述（中文，一句话说明这张图应该展示什么主体/场景/氛围）

格式：
关键词: <英文关键词>
描述: <中文描述>

直接输出，不要其他解释。"""
                try:
                    analysis = self.chat(prompt, temperature=0.3)
                    # 解析关键词和描述
                    query = ""
                    desc_cn = ""
                    for line in analysis.split("\n"):
                        line = line.strip()
                        if line.lower().startswith("关键词:") or line.lower().startswith("keyword:"):
                            query = line.split(":", 1)[1].strip()
                        elif line.startswith("描述:") or line.lower().startswith("description:"):
                            desc_cn = line.split(":", 1)[1].strip()
                    # 如果解析失败，用整段分析作为关键词
                    if not query:
                        query = analysis.strip()[:100]
                    results.append({"index": idx, "query_or_prompt": query, "description_cn": desc_cn})
                    print(f"[image] 配图位置{idx+1}搜图关键词: {query}")
                except Exception as e:
                    print(f"[image] 配图位置{idx+1}分析失败，回退原描述: {e}")
                    results.append({"index": idx, "query_or_prompt": description, "description_cn": description})

            else:
                # AI生图模式：生成非常专业的英文生图prompt（单段连贯文本）
                prompt = f"""你是一个专业的AI绘画提示词工程师。请分析以下文章中某个配图位置的上下文，生成专业的AI绘画提示词。

【配图位置的章节标题】：{position_title}
【配图位置的前文】：{context_before[:300]}
【配图位置的后文】：{context_after[:300]}
【原配图说明】：{description}

请输出一段流畅、连贯的英文AI绘画提示词（50-100词），把以下要素自然融入同一段描述中：
主体内容（具体是什么，细节丰富）、场景环境、艺术风格（写实/插画/科技感/极简/水彩/油画等）、
色调（冷暖/明暗/主色调）、构图（特写/全景/居中/三分法等）、光线（自然光/逆光/柔光/霓虹光等）、
画质（8K/高细节/电影感等）、氛围（宁静/紧张/温暖/科技感/神秘等）

【硬性要求】
- 必须是一段连贯的自然语言描述
- 【禁止】编号、禁止列表、禁止"1. 主体："这类要素标签
- 直接输出提示词本身，不要任何解释、不要引号"""
                try:
                    analysis = self.chat(prompt, temperature=0.7)
                    # 兜底清洗：即使模型仍输出编号/标签，也转成流畅单段
                    clean = self._clean_image_prompt(analysis)
                    results.append({"index": idx, "query_or_prompt": clean, "description_cn": description})
                    print(f"[image] 配图位置{idx+1}AI生图prompt生成完成（{len(clean)}字符）")
                except Exception as e:
                    print(f"[image] 配图位置{idx+1}分析失败，回退原描述: {e}")
                    results.append({"index": idx, "query_or_prompt": description, "description_cn": description})

        return results

    def _clean_image_prompt(self, raw: str) -> str:
        """
        清洗 AI 绘画提示词：
        - 去掉 "1. 主体：" "2、场景：" 这类编号/标签前缀
        - 去掉 "- " "* " 列表符号
        - 把多行结构化内容合并成一段流畅的英文提示词
        - 去掉首尾引号
        """
        if not raw:
            return raw
        parts = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 去编号前缀：1. / 1、 / 1) / 1）
            line = re.sub(r'^\d+[.、)）:：\s]+', '', line)
            # 去列表符号
            line = re.sub(r'^[-*•]\s*', '', line)
            # 去"主体：""Subject:"这类要素标签前缀
            line = re.sub(
                r'^(主体|场景|风格|色调|构图|光线|画质|氛围|细节|subject|scene|style|color'
                r'|colour|composition|lighting|quality|atmosphere|detail)\s*[：:]\s*',
                '', line, flags=re.IGNORECASE
            )
            line = line.strip().strip('"\'`"')
            if line:
                parts.append(line)
        merged = " ".join(parts)
        return merged if merged else raw

    def get_image_by_query(self, query_or_prompt: str, image_source: str) -> Optional[str]:
        """
        根据已分析好的关键词/prompt直接获取图片（不再做文字转换）
        image_source: "api"（搜图）或 "ai"（AI生图）
        """
        stripped = (query_or_prompt or "").strip()
        if not stripped or len(stripped) < 2:
            return None

        if image_source == "api":
            # 搜图：query_or_prompt 已是 analyze_image_needs 分析好的关键词，直接搜索，不再二次转换
            # 若为纯中文（分析失败回退原描述的情况），先转成英文关键词
            if not re.search(r'[a-zA-Z]', stripped):
                stripped = self.generate_image_prompt(stripped, "api")
            image_url, success = self.search_image_with_retry(
                stripped, max_retries=2, use_direct_query=True
            )
            return image_url
        else:
            # AI生图：先清洗 prompt（去编号/标签），再传给生图模型，避免结构化文本导致画面偏离
            clean_prompt = self._clean_image_prompt(stripped)
            return self.generate_image_dashscope(clean_prompt)

    def process_images(self, content: str, image_source: str, task_id: int = None) -> Tuple[str, List[str]]:
        """
        配图主入口（优化版）：
        1. 从正文中提取配图标记 + 上下文
        2. LLM 深度分析每个配图位置，生成专业的搜图关键词或AI生图prompt
        3. 根据配图方式获取图片
        4. 持久化图片到本地（文件名带任务ID+运行唯一标识，避免跨任务/跨次生成复用旧图）
        5. 把配图标记替换成图片markdown
        6. 配图失败的位置改成纯文本过渡句

        返回：(插入图片后的正文, 成功插入的图片URL列表)
        """
        # 本次配图运行唯一标识：保证每次生成的图片文件名都不同，不复用历史任务/历史次生成的图片
        import uuid
        run_id = uuid.uuid4().hex[:8]
        file_prefix = f"task{task_id}_{run_id}" if task_id is not None else f"img_{run_id}"

        # 1. 提取配图标记 + 上下文
        markers = self.extract_markers_with_context(content)
        if not markers:
            print("[image] 未找到配图标记，跳过配图")
            return content, []

        print(f"[image] 找到 {len(markers)} 个配图位置，开始分析...")

        # 2. LLM 深度分析每个配图位置
        analyzed = self.analyze_image_needs(markers, image_source)
        analyzed_map = {a["index"]: a for a in analyzed}

        # 3. 并发获取图片（搜图/生图均为 I/O 等待，线程池并行可显著缩短总耗时）
        #    max_workers=4：兼顾并发收益与 API 限流（百炼生图 / Pexels 等）
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_image(marker_item: Dict) -> Optional[str]:
            idx = marker_item["index"]
            analysis = analyzed_map.get(idx, {})
            query_or_prompt = analysis.get("query_or_prompt", "")
            if not query_or_prompt:
                print(f"[image] 配图位置{idx+1}无有效关键词/prompt，跳过")
                return None
            print(f"[image] 正在获取第{idx+1}/{len(markers)}张配图...")
            url = self.get_image_by_query(query_or_prompt, image_source)
            if not url:
                print(f"[image] 配图位置{idx+1}获取失败")
            return url

        with ThreadPoolExecutor(max_workers=4) as pool:
            image_urls = list(pool.map(_fetch_image, markers))

        # 4. 持久化图片到本地（文件名唯一，避免复用历史图片）
        persisted_urls = []
        for i, url in enumerate(image_urls):
            if url:
                persisted = self.persist_image(url, f"{file_prefix}_{i+1}")
                persisted_urls.append(persisted)
            else:
                persisted_urls.append(None)

        # 5. 把配图标记替换成图片
        content_with_images, inserted_urls = self.insert_images_by_markers(
            content, markers, persisted_urls
        )

        # 6. 配图失败的位置改成纯文本过渡句
        failed_markers = [markers[i] for i in range(len(markers)) if not persisted_urls[i]]
        if failed_markers:
            print(f"[image] 有{len(failed_markers)}处配图未找到，正在调整为文字描述...")
            for marker in failed_markers:
                desc_cn = analyzed_map.get(marker["index"], {}).get("description_cn", marker["description"])
                content_with_images = self.replace_image_with_text(
                    content_with_images, marker["position_title"], desc_cn
                )

        # 保存成功的图片URL
        success_urls = [u for u in inserted_urls if u]
        print(f"[image] 配图完成：成功{len(success_urls)}张，失败{len(failed_markers)}处")

        return content_with_images, success_urls
