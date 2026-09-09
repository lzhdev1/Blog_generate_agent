from typing import Optional

from src.blog_agent.agent.agents.base_agent import BaseAgent


class OutlinerAgent(BaseAgent):
    """大纲师 Agent：负责生成博客大纲"""

    name = "outliner"
    role = "大纲师"
    system_prompt = """你是一个专业的内容策划编辑，擅长：
1. 根据主题和调研结果设计清晰的文章结构
2. 安排合理的章节顺序和逻辑递进
3. 确保大纲覆盖核心内容且有独特角度
4. 输出规范的 markdown 格式大纲"""
    model_config_key = "llm_model_outliner"

    def generate_outline(
        self,
        selected_title: str,
        research: str = "",
        need_image: bool = False,
        image_source: str = "",
    ) -> str:
        """生成大纲，如果需要配图则在大纲中标注配图位置"""
        research_section = ""
        if research:
            research_section = f"""
以下是大纲调研结果，请参考这些分析，避免和现有文章结构重复：
{research}
"""

        image_section = ""
        if need_image:
            if image_source == "api":
                image_desc = "请在需要配图的章节前，用HTML注释标注配图位置和搜索关键词，格式：<!-- 配图：搜索关键词 -->"
            else:
                image_desc = "请在需要配图的章节前，用HTML注释标注配图位置和画面描述，格式：<!-- 配图：画面描述 -->"
            image_section = f"""
配图要求：本文需要配图。{image_desc}
注意：注释要放在对应章节标题的前一行，不要影响大纲的正常阅读。
"""

        prompt = f"""请以"{selected_title}"为标题，生成一份详细的博客文章大纲。
{research_section}
{image_section}
要求：
1. 使用 markdown 格式，用 ## 表示一级章节，### 表示二级小节
2. 大纲结构清晰，包含引言、主体内容（3-5个章节）、总结
3. 每个章节下面简要说明要写什么内容
4. 参考调研结果，避免结构重复，增加独特内容
5. 直接输出大纲，不要其他解释

请直接输出大纲："""
        return self.chat(prompt, temperature=0.7)
