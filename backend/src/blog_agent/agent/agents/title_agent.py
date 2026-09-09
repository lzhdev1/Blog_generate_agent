from typing import List

from src.blog_agent.agent.agents.base_agent import BaseAgent


class TitleAgent(BaseAgent):
    """标题 Agent：负责生成博客标题"""

    name = "title"
    role = "标题策划"
    system_prompt = """你是一个专业的标题策划，擅长：
1. 根据主题和调研结果，生成吸引人的标题
2. 避免和现有标题重复，选择独特角度
3. 标题简洁有力，适合技术博客
4. 控制标题长度，不超过30字"""
    model_config_key = "llm_model_outliner"  # 和大纲师用同一个模型

    def generate_titles(self, topic: str, research: str = "") -> List[str]:
        """生成3个标题"""
        research_section = ""
        if research:
            research_section = f"""
以下是标题调研结果，请参考这些分析，避免和现有标题重复，选择独特角度：
{research}
"""

        prompt = f"""请为主题"{topic}"生成3个吸引人的博客文章标题。
{research_section}
要求：
1. 每个标题不超过30字
2. 标题要有吸引力，适合技术博客
3. 参考调研结果，避免重复，选择独特角度
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
