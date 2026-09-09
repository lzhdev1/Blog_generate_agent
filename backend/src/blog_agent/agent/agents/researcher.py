from src.blog_agent.agent.agents.base_agent import BaseAgent


class ResearcherAgent(BaseAgent):
    """研究员 Agent：负责调研、搜索资料、分析同类文章"""

    name = "researcher"
    role = "研究员"
    system_prompt = """你是一个专业的技术研究员，擅长：
1. 分析技术主题的现状和趋势
2. 总结同类文章的常见角度和结构
3. 提取关键信息和数据
4. 给出独特的切入角度建议

你的回答要简洁、有洞察力，不要泛泛而谈。"""
    model_config_key = "llm_model_researcher"

    def research_for_titles(self, topic: str) -> str:
        """标题调研：分析同类文章标题，避免重复，提供角度建议"""
        prompt = f"""请帮我做一个关于"{topic}"的博客标题调研。

请基于你的知识，分析以下内容：
1. 这个主题目前有哪些常见的写作角度？
2. 同类文章的标题通常用什么风格？（数字型、疑问型、干货型等）
3. 有哪些标题关键词比较热门？
4. 为了避免重复，建议从哪些独特角度切入？

请用简洁的语言总结，不要超过300字。"""
        return self.chat(prompt, temperature=0.5)

    def research_for_outline(self, topic: str, selected_title: str) -> str:
        """大纲调研：分析同类文章大纲结构，避免重复"""
        prompt = f"""请帮我做一个博客大纲调研。

主题：{topic}
拟定标题：{selected_title}

请基于你的知识，分析以下内容：
1. 同类文章通常包含哪些章节？
2. 常见的大纲结构是什么样的？
3. 有哪些内容是必须包含的？
4. 为了避免和现有文章重复，建议增加哪些独特内容或角度？

请用简洁的语言总结，不要超过300字。"""
        return self.chat(prompt, temperature=0.5)
