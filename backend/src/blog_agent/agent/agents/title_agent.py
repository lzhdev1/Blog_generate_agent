from typing import List

from src.blog_agent.agent.agents.base_agent import BaseAgent


class TitleAgent(BaseAgent):
    """标题 Agent：负责生成博客标题"""

    name = "title"
    role = "标题策划"
    system_prompt = """你是一个专业的标题策划，擅长：
1. 根据主题和调研结果，生成吸引人的标题
2. 先分析调研结果，判断文章所属类型，标题风格和用词需符合该类型
3. 切入角度完全依据调研结果选择，优先采用重复度低、有差异化的角度，避免和已有标题重复
4. 标题简洁有力，不超过30字"""
    model_config_key = "llm_model_title"  # 标题策划专用模型

    def generate_titles(self, topic: str, research: str = "") -> List[str]:
        """生成3个标题"""
        research_section = ""
        if research:
            research_section = f"""
以下是标题调研结果，必须严格依据此结果进行创作：
{research}
"""

        prompt = f"""请为主题"{topic}"生成3个吸引人的博客文章标题。
{research_section}
要求：
1. 先分析调研结果，判断这篇文章属于什么类型（如技术教程、生活经验、财经分析、情感随笔等），3个标题的风格和用词都要符合该类型
2. 每个标题不超过30字
3. 切入角度必须从调研结果中选择，优先采用"重复度低、有差异化"的角度，避开调研结果中标明的雷区
4. 直接输出3个标题，每行一个，不要编号，不要其他解释

请直接输出标题："""

        resp = self.chat(prompt, temperature=0.8)

        # 解析返回结果：按行分割，去掉空行和编号
        titles = []
        for line in resp.strip().split("\n"):
            line = line.strip()
            # 去掉可能的编号（1. 2. 3. 或 1、2、3、）
            if line and line[0].isdigit():
                line = line.lstrip("0123456789.、 ")
            if line:
                titles.append(line)

        # 确保至少返回3个，不足则补全
        while len(titles) < 3:
            titles.append(f"{topic}相关博客标题{len(titles) + 1}")

        return titles[:3]
