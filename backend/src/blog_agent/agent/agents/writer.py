from typing import Optional

from src.blog_agent.agent.agents.base_agent import BaseAgent


class WriterAgent(BaseAgent):
    """写手 Agent：负责根据大纲撰写正文"""

    name = "writer"
    role = "写手"
    system_prompt = """你是一个专业的文章写手，擅长：
1. 根据大纲撰写结构清晰、逻辑严谨、可读性强的文章
2. 文章的语言风格、专业深度由大纲和调研资料决定（可能是技术科普、行业分析、生活随笔、财经解读等），不要默认写成技术文章
3. 适当举例，让文章更生动
4. 保持流畅、自然的文风
5. 输出规范的 markdown 格式"""
    model_config_key = "llm_model_writer"

    def generate_content(
        self,
        outline: str,
        selected_title: str,
        review_feedback: str = "",
        content_research: str = "",
        word_count: int = None,
        level: str = None,
        content_extra_requirements: str = None,
    ) -> str:
        """
        生成正文
        如果有审稿意见，根据意见修改
        如果有正文调研结果，参考调研中的数据和来源
        word_count/level/content_extra_requirements 来自大纲确认页的用户配置
        """
        review_section = ""
        if review_feedback:
            review_section = f"""
以下是审稿意见，请根据这些意见修改文章：
{review_feedback}
"""

        research_section = ""
        if content_research:
            # 截断保护：旧任务调研可能很长，写手只需要关键素材
            if len(content_research) > 10000:
                content_research = content_research[:10000] + "\n...（调研内容过长，已截断）"
            research_section = f"""
以下是写作前的调研结果，必须严格依据其中的数据、版本号、案例和权威来源进行创作，确保文章内容的真实性、准确性和时效性：
{content_research}
"""

        # 字数要求（来自用户在大纲确认页的配置）
        word_count_section = ""
        if word_count:
            word_count_section = f"""
字数要求：全文目标约 {word_count} 字，请根据字数合理安排各章节篇幅，不要明显超出或不足。
"""
        else:
            word_count_section = "字数要求：全文不少于800字。\n"

        # 专业水平要求（来自用户在大纲确认页的配置）
        level_map = {
            "general": "入门科普，语言通俗易懂，避免过多专业术语，适合零基础读者",
            "medium": "中等深度，有一定技术细节，但不过于晦涩，适合有基础的读者",
            "advanced": "高级深度，包含较多技术细节和原理分析，适合进阶读者",
            "professional": "专业级，深入技术原理，包含代码/配置/架构分析，适合专业从业者",
        }
        level_section = ""
        if level and level in level_map:
            level_section = f"""
专业水平：{level_map[level]}。请根据这个深度调整用词、技术密度和内容深度。
"""

        # 对正文的额外要求（来自用户在大纲确认页的配置）
        extra_section = ""
        if content_extra_requirements and content_extra_requirements.strip():
            extra_section = f"""
用户对正文的额外要求：{content_extra_requirements.strip()}
请在正文中充分体现这些要求。
"""

        prompt = f"""请根据以下大纲，写一篇完整的博客文章。

文章标题：{selected_title}
{research_section}
{word_count_section}
{level_section}
{extra_section}
文章大纲：
{outline}
{review_section}
【创作流程】
1. 先仔细阅读并理解大纲结构、调研结果、用户配置
2. 如果有审稿意见，先逐条分析审稿意见指出的问题，明确哪些地方需要修改、怎么修改
3. 再开始撰写正文，严格遵守以下所有硬约束

【硬约束（必须严格遵守，违反任何一条都视为失败）】

1. 【禁止修改标题】文章标题"{selected_title}"是用户选择的最终标题，不得修改、替换、缩写或在正文中使用其他标题。正文不要输出标题行（标题已在页面顶部展示），直接从大纲第一个章节开始。

2. 【严格遵守大纲结构】
   - 必须严格使用大纲中的章节标题，不得增删、合并、修改或重命名任何标题文字
   - 标题层级（#/##/###）必须与大纲完全一致
   - 章节顺序必须与大纲一致，不得调换
   - 不得添加大纲中不存在的额外标题（如"引言""前言""总结"等，除非大纲中已有）
   - 每个章节的内容必须围绕大纲中该章节的说明来写，不得偏离

3. 【严格结合调研结果】
   - 必须严格依据调研结果中的数据、版本号、案例和权威来源进行创作
   - 不得编造调研结果中不存在的具体数据、案例或来源
   - 调研结果中标注"来源未明确"或"时间未标注"的资料，使用时需谨慎，不得作为权威数据引用
   - 调研结果中标注"本章节无需外部调研资料"的章节，基于已有知识撰写即可
   - 文章风格与目标读者匹配（参考调研结果中同类文章的定位和文风），不要默认写成技术博客

4. 【严格遵守用户配置】
   - 字数要求必须严格遵守，不要明显超出或不足
   - 专业水平必须严格遵守，根据指定深度调整用词、技术密度和内容深度
   - 对正文的额外要求必须充分体现

5. 【认真对待审稿意见（如有）】
   - 如果有审稿意见，必须先逐条分析意见指出的问题，明确每个问题对应的修改位置和修改方式
   - 修改时保留原文中正确的部分，只修改有问题的部分，不要全盘重写
   - 审稿意见中提到的配图问题，调整配图描述使其更容易搜到相关图片；如果某个位置确实不适合配图，可以删掉配图注释改成纯文本过渡
   - 审稿意见中提到的内容不准确、数据错误、结构问题、风格问题等，必须逐一修正

【其他要求】
6. 使用 markdown 格式，内容详实，逻辑清晰，每个章节都要有实质内容
7. 保留大纲中的配图注释标记（<!-- 配图：... -->），放在对应章节标题之后
8. 除非大纲或调研明确要求展示代码（如教程、API文档类），否则不要插入代码块；确需展示数字公式时，使用 LaTeX 格式：行内公式用 $...$，独立公式用 $$...$$
9. 直接输出文章正文，不要其他解释，不要输出"以下是文章"等引导语

请直接输出文章正文："""
        # 正文可能较长（800字以上+markdown+配图注释），设大一些防止被截断
        return self.chat(prompt, temperature=0.8, max_tokens=8192)

    def generate_thoughts(
        self,
        selected_title: str,
        outline: str,
        content_research: str = "",
        word_count: int = None,
        level: str = None,
        content_extra_requirements: str = None,
    ) -> str:
        """
        生成写作思路：在动笔前阐述创作逻辑，展示给用户
        """
        research_section = ""
        if content_research:
            if len(content_research) > 8000:
                content_research = content_research[:8000] + "\n...（调研内容过长，已截断）"
            research_section = f"""
以下是写作前的调研结果，请基于其中的资料规划写作思路：
{content_research}
"""

        # 用户配置摘要
        config_summary = ""
        parts = []
        if word_count:
            parts.append(f"目标约{word_count}字")
        if level:
            level_labels = {"general": "入门", "medium": "中等", "advanced": "高级", "professional": "专业"}
            parts.append(f"专业水平：{level_labels.get(level, level)}")
        if content_extra_requirements and content_extra_requirements.strip():
            parts.append(f"额外要求：{content_extra_requirements.strip()}")
        if parts:
            config_summary = "用户写作配置：" + "；".join(parts) + "\n"

        prompt = f"""请作为文章写手，在正式动笔前先阐述你的写作思路（200-300字），让读者直观了解你的创作逻辑。内容需包含：
1. 文章定位与文风：根据调研结果判断这是哪种类型的文章（如技术科普、行业分析、生活随笔、财经解读等），采用什么文风，目标读者是谁
2. 论证主线：打算如何组织大纲中的章节，各部分之间的逻辑关系
3. 关键素材：计划重点使用调研中的哪些数据、案例和来源，并标注这些资料的发布时间
4. 写作边界：明确哪些内容不使用（如过时的数据、与大纲无关的内容）

文章标题：{selected_title}
{research_section}
{config_summary}
文章大纲：
{outline}

请直接输出写作思路，不要输出正文："""
        return self.chat(prompt, temperature=0.6)
