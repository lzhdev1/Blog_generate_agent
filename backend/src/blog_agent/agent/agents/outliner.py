from typing import Optional

from src.blog_agent.agent.agents.base_agent import BaseAgent


class OutlinerAgent(BaseAgent):
    """大纲师 Agent：负责生成博客大纲"""

    name = "outliner"
    role = "大纲师"
    system_prompt = """你是一个资深的博客内容策划，擅长写技术博客和干货文章。你懂读者喜欢看什么：
1. 博客不是论文，结构要轻松、有吸引力，不要用"1.1 研究背景"这种学术化标题
2. 读者喜欢"是什么→为什么→怎么做→实战案例→避坑指南"这种递进结构
3. 每个章节的小标题要吸引人，让人一看就想往下读
4. 内容要实用、有干货，不要空泛的理论
5. 适当加入对比、实战、踩坑经验，让文章更有价值"""
    model_config_key = "llm_model_outliner"

    def generate_outline(
        self,
        selected_title: str,
        research: str = "",
        need_image: bool = False,
        image_source: str = "",
        word_count: int = None,
        level: str = None,
        extra_requirements: str = None,
    ) -> str:
        """生成大纲，如果需要配图则在大纲中标注配图位置"""
        research_section = ""
        if research:
            research_section = f"""
以下是同类文章的调研结果，请参考这些分析，避免结构重复，找到独特的切入点：
{research}
"""

        image_section = ""
        if need_image:
            if image_source == "api":
                image_desc = "在需要配图的章节前，用HTML注释标注配图位置和搜索关键词，格式：<!-- 配图：搜索关键词 -->"
            else:
                image_desc = "在需要配图的章节前，用HTML注释标注配图位置和画面描述，格式：<!-- 配图：画面描述 -->"
            image_section = f"""
配图要求：本文需要配图。{image_desc}
注释放在对应章节标题的前一行，不影响大纲阅读。
"""

        # 字数要求
        word_count_section = ""
        if word_count:
            word_count_section = f"""
字数要求：全文目标约 {word_count} 字，请根据字数合理安排章节数量和每章篇幅。
"""

        # 专业水平要求
        level_map = {
            "general": "入门科普，语言通俗易懂，避免过多专业术语，适合零基础读者",
            "medium": "中等深度，有一定技术细节，但不过于晦涩，适合有基础的读者",
            "advanced": "高级深度，包含较多技术细节和原理分析，适合进阶读者",
            "professional": "专业级，深入技术原理，包含代码/配置/架构分析，适合专业从业者",
        }
        level_section = ""
        if level and level in level_map:
            level_section = f"""
专业水平：{level_map[level]}。请根据这个深度调整大纲的技术密度和内容深度。
"""

        # 额外要求
        extra_section = ""
        if extra_requirements and extra_requirements.strip():
            extra_section = f"""
用户额外要求：{extra_requirements.strip()}
请在大纲中充分体现这些要求。
"""

        prompt = f"""请以"{selected_title}"为标题，写一份博客文章大纲。
{research_section}
{image_section}
{word_count_section}
{level_section}
{extra_section}
【重要】这是博客，不是论文！请遵守以下要求：

1. 标题风格：用吸引人的博客式小标题，不要学术化
   ❌ 错误：1.1 研究背景、2.3 系统设计
   ✅ 正确：为什么需要它？、核心原理一次讲透、实战：从零搭建、踩坑指南

2. 结构建议（可灵活调整）：
   - 开头：用痛点或场景引入，让读者知道为什么要读这篇
   - 主体：3-5个核心章节，循序渐进，从入门到实战
   - 结尾：总结要点 + 延伸思考或下一步

3. 每个章节下面用1-2句话说明要写什么内容，确保有干货

4. 用 markdown 格式，## 表示大章节，### 表示小章节

5. 直接输出大纲，不要其他解释

请直接输出大纲："""
        return self.chat(prompt, temperature=0.7)
