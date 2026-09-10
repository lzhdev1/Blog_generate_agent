import re
import json
import os
import requests
from typing import List, Dict, Optional, Tuple

from src.blog_agent.agent.agents.base_agent import BaseAgent
from config.settings import settings


class ImageAgent(BaseAgent):
    """配图 Agent：负责生成配图提示词、搜索/生成图片、插入正文"""

    name = "image"
    role = "配图设计师"
    system_prompt = """你是一个专业的配图设计师，擅长：
1. 根据文章内容分析哪些位置需要配图
2. 生成精准的图片搜索关键词或AI绘画提示词
3. 确保图片风格和文章内容匹配"""
    model_config_key = "llm_model_formatter"  # 用便宜的模型生成提示词

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

    def optimize_image_query(self, description: str) -> str:
        """
        搜索失败时，把配图描述改得更通用、更容易搜到
        比如"性能对比图表" → "数据 科技 办公"
        """
        prompt = f"""以下配图描述在图片库搜索不到，请把它改得更通用、更抽象，更容易在摄影图片库搜到。
要求：
1. 去掉具体的图表、示意图、架构图等搜不到的类型
2. 改成相关的场景、物品、氛围描述
3. 输出英文关键词，用空格分隔，不超过8个单词
4. 直接输出关键词，不要其他解释

原描述：{description}
优化后的关键词："""
        return self.chat(prompt, temperature=0.3)

    def search_image_with_retry(self, description: str, max_retries: int = 2) -> Tuple[Optional[str], bool]:
        """
        带重试的图片搜索
        返回：(图片URL或None, 是否搜索成功)
        第一次用原描述，失败后LLM优化描述再试，最多max_retries次
        """
        # 第一次：用原描述生成关键词
        query = self.generate_image_prompt(description, "api")
        image_url = self.search_image_pexels(query)
        if not image_url:
            image_url = self.search_image_unsplash(query)

        if image_url:
            return image_url, True

        # 重试：优化描述后再搜
        for attempt in range(max_retries):
            print(f"配图搜索失败（第{attempt+1}次），正在优化描述重试...")
            optimized_query = self.optimize_image_query(description)
            image_url = self.search_image_pexels(optimized_query)
            if not image_url:
                image_url = self.search_image_unsplash(optimized_query)
            if image_url:
                return image_url, True

        return None, False

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

    def search_image_unsplash(self, query: str) -> Optional[str]:
        """
        调用 Unsplash API 搜索图片
        需要配置 UNSPLASH_ACCESS_KEY
        返回图片URL，失败返回None
        """
        api_key = getattr(settings, "unsplash_access_key", None)
        if not api_key:
            return None

        try:
            url = "https://api.unsplash.com/search/photos"
            params = {
                "query": query,
                "per_page": 1,
                "orientation": "landscape",
            }
            headers = {"Authorization": f"Client-ID {api_key}"}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("results"):
                    return data["results"][0]["urls"]["regular"]
        except Exception as e:
            print(f"Unsplash搜索失败: {e}")
        return None

    def search_image_pexels(self, query: str) -> Optional[str]:
        """
        调用 Pexels API 搜索图片
        需要配置 PEXELS_API_KEY
        返回图片URL，失败返回None
        """
        api_key = getattr(settings, "pexels_api_key", None)
        if not api_key:
            return None

        try:
            url = "https://api.pexels.com/v1/search"
            params = {
                "query": query,
                "per_page": 1,
                "orientation": "landscape",
            }
            headers = {"Authorization": api_key}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("photos"):
                    return data["photos"][0]["src"]["large"]
        except Exception as e:
            print(f"Pexels搜索失败: {e}")
        return None

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
            resp = requests.post(url, headers=headers, json=data, timeout=120)
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
            resp = requests.post(url, headers=headers, json=data, timeout=30)
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
                resp = requests.get(url, headers=headers, timeout=10)
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
        if image_source == "api":
            # 搜索图片：带重试，失败时优化描述再搜
            image_url, success = self.search_image_with_retry(description, max_retries=2)
            return image_url
        else:
            # AI生成
            prompt = self.generate_image_prompt(description, "ai")
            return self.generate_image_dashscope(prompt)

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
