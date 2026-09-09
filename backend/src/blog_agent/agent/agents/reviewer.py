import json
from typing import Dict

from src.blog_agent.agent.agents.base_agent import BaseAgent


class ReviewerAgent(BaseAgent):
    """审稿 Agent：负责检查文章质量，给出修改意见"""

    name = "reviewer"
    role = "审稿编辑"
    system_prompt = """你是一个严格的资深审稿编辑，擅长：
1. 检查文章结构是否清晰、逻辑是否连贯
2. 发现事实错误、技术错误、逻辑漏洞
3. 指出语言表达问题、错别字、格式问题
4. 给出具体、可操作的修改建议
5. 严格把关，不轻易通过

你的审稿要客观、具体，不要泛泛而谈。"""
    model_config_key = "llm_model_reviewer"

    def review_content(self, content: str, selected_title: str) -> Dict:
        """
        审稿，返回结构化结果
        返回：{"passed": bool, "score": int, "issues": list, "suggestions": list, "feedback": str}
        """
        prompt = f"""请审阅以下博客文章。

文章标题：{selected_title}

文章内容：
{content}

请从以下维度审稿：
1. 结构清晰度（章节安排、逻辑递进）
2. 内容准确性（事实、技术、数据是否正确）
3. 表达流畅度（语言、错别字、格式）
4. 内容充实度（是否有实质内容，还是空泛）

请严格按照以下JSON格式输出，不要输出其他内容：
{{
    "passed": true或false,
    "score": 0-100的整数评分,
    "issues": ["问题1", "问题2", ...],
    "suggestions": ["修改建议1", "修改建议2", ...],
    "feedback": "总体评价和修改说明"
}}

注意：
- 80分以上且没有严重问题才能通过（passed=true）
- 有事实错误、逻辑混乱、内容空洞等严重问题必须不通过
- issues和suggestions要具体，不要写"内容不错"这种空话"""

        resp = self.chat(prompt, temperature=0.3)

        # 解析 JSON 结果
        try:
            # 尝试提取 JSON（可能被 markdown 代码块包裹）
            resp_clean = resp.strip()
            if resp_clean.startswith("```"):
                # 去掉代码块标记
                lines = resp_clean.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                resp_clean = "\n".join(lines)

            result = json.loads(resp_clean)
            return {
                "passed": bool(result.get("passed", False)),
                "score": int(result.get("score", 0)),
                "issues": result.get("issues", []),
                "suggestions": result.get("suggestions", []),
                "feedback": result.get("feedback", ""),
            }
        except (json.JSONDecodeError, ValueError):
            # 解析失败，默认不通过，把原始返回作为反馈
            return {
                "passed": False,
                "score": 0,
                "issues": ["审稿结果解析失败"],
                "suggestions": [],
                "feedback": resp[:500],
            }
