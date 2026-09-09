from typing import Optional

from src.blog_agent.agent.agents.base_agent import BaseAgent


class WriterAgent(BaseAgent):
    """写手 Agent：负责根据大纲撰写正文"""

    name = "writer"
    role = "写手"
    system_prompt = """你是一个专业的技术博客写手，擅长：
1. 根据大纲撰写结构清晰、逻辑严谨的文章
2. 用通俗易懂的语言解释复杂概念
3. 适当举例，让文章更生动
4. 保持专业但不枯燥的文风
5. 输出规范的 markdown 格式"""
    model_config_key = "llm_model_writer"

    def generate_content(
        self,
        outline: str,
        selected_title: str,
        review_feedback: str = "",
        content_research: str = "",
    ) -> str:
        """
        生成正文
        如果有审稿意见，根据意见修改
        如果有正文调研结果，参考调研中的数据和来源
        """
        review_section = ""
        if review_feedback:
            review_section = f"""
以下是审稿意见，请根据这些意见修改文章：
{review_feedback}
"""

        research_section = ""
        if content_research:
            research_section = f"""
以下是写作前的调研结果，请参考其中的最新数据、版本号和权威来源，确保文章内容的准确性和时效性：
{content_research}
"""

        prompt = f"""请根据以下大纲，写一篇完整的博客文章。

文章标题：{selected_title}
{research_section}
文章大纲：
{outline}
{review_section}
要求：
1. 使用 markdown 格式
2. 内容详实，逻辑清晰，每个章节都要有实质内容
3. 语言通顺，适合技术博客阅读
4. 字数不少于800字
5. 参考调研结果中的最新数据和版本号，不要使用过时的信息
6. 【重要】必须严格使用大纲中的章节标题，不得增删、合并、修改或重命名任何标题文字，标题层级（#/##/###）也必须保持一致
7. 保留大纲中的配图注释标记（<!-- 配图：... -->），放在对应章节标题之后
8. 如果审稿意见中提到配图不匹配或有问题，请调整配图描述，使其更容易搜到相关图片；如果某个位置确实不适合配图，可以删掉配图注释，改成纯文本过渡
9. 直接输出文章正文，不要重复标题，不要其他解释

请直接输出文章正文："""
        return self.chat(prompt, temperature=0.8)
