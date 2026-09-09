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
        调用百炼通义万相生成图片
        需要配置 DASHSCOPE_API_KEY（和LLM共用一个key即可）
        返回图片URL，失败返回None
        """
        api_key = settings.llm_api_key
        model = getattr(settings, "image_gen_model", "wanx2.1-t2i-turbo")

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
                    # 轮询任务结果
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
        # 生成提示词/关键词
        prompt = self.generate_image_prompt(description, image_source)

        if image_source == "api":
            # 优先用 Pexels，失败用 Unsplash
            image_url = self.search_image_pexels(prompt)
            if not image_url:
                image_url = self.search_image_unsplash(prompt)
            return image_url
        else:
            # AI生成
            return self.generate_image_dashscope(prompt)

    # ============================================================
    # 6. 把图片插入正文
    # ============================================================

    def insert_images_to_content(
        self,
        content: str,
        image_positions: List[Dict],
        image_urls: List[Optional[str]],
    ) -> Tuple[str, List[str]]:
        """
        把图片插入正文对应位置
        返回：(插入图片后的正文, 成功插入的图片URL列表)
        """
        result = content
        inserted_urls = []

        for i, pos in enumerate(image_positions):
            if i >= len(image_urls) or not image_urls[i]:
                continue

            image_url = image_urls[i]
            # 在正文找到对应章节标题，在标题后插入图片
            position = pos["position"]
            # 转义特殊字符
            escaped_position = re.escape(position)
            pattern = f'(^#{{1,4}}\\s+{escaped_position}\\s*$)'
            replacement = f'\\1\n\n![{pos["description"]}]({image_url})\n'

            new_result = re.sub(pattern, replacement, result, count=1, flags=re.MULTILINE)
            if new_result != result:
                result = new_result
                inserted_urls.append(image_url)
            else:
                # 找不到对应标题，在正文末尾追加
                result += f'\n\n![{pos["description"]}]({image_url})\n'
                inserted_urls.append(image_url)

        return result, inserted_urls
