import re
from typing import List, Optional

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

    # 模型可能照抄格式示例产生的无效占位词（命中即判定配图标记无效）
    INVALID_IMAGE_MARKERS = {
        "搜索关键词", "具体搜索关键词", "图片搜索关键词", "配图关键词",
        "画面描述", "配图描述", "图片描述", "配图位置和搜索关键词",
        "关键词", "描述", "search keywords", "image description",
    }

    def generate_outline(
        self,
        selected_title: str,
        research: str = "",
        need_image: bool = False,
        article_style: str = "",
        article_style_custom: str = "",
        extra_requirements: str = None,
    ) -> str:
        """
        生成大纲
        - 严格遵守：用户选择的标题、是否配图、文章风格
        - 认真分析：大纲调研结果（同类文章结构）和大纲制定建议（推荐哪种结构）
        - 参考：对大纲的额外要求
        - 配图注释统一格式：<!-- 配图：配图内容建议 -->（描述主体/场景/风格，20-50字）
        """
        # 文章风格描述
        style_map = {
            "popular_science": "科普类（通俗易懂，面向大众读者，结构轻松有趣）",
            "technical": "技术类（有技术深度，面向有基础的读者，结构严谨实用）",
            "essay": "论文类（学术严谨，论证严密，结构规范完整）",
            "prose": "散文类（文笔优美，抒情叙事，结构自由流畅）",
            "note": "笔记类（简洁实用，要点清晰，结构条理分明）",
        }
        style_desc = style_map.get(article_style, "")
        if article_style == "custom" and article_style_custom:
            style_desc = f"自定义风格：{article_style_custom}"

        style_section = ""
        if style_desc:
            style_section = f"""
文章风格：{style_desc}
（【严格遵守】大纲的结构类型、章节标题风格、内容深度都必须符合此文章风格的特点）
"""

        # 调研结果（认真分析）
        research_section = ""
        if research:
            research_section = f"""
以下是同类文章的大纲调研结果，【必须认真分析】其中的结构类型分析和大纲制定建议，据此规划章节结构，避免与同类文章雷同：
{research}
"""

        # 配图要求（统一格式：配图内容建议）
        image_section = ""
        if need_image:
            image_section = f"""
配图要求：本文需要配图。请在需要配图的章节标题后，用HTML注释标注配图位置和配图内容建议。

【格式要求】
- 注释格式：<!-- 配图：<配图内容建议> -->
- 配图内容建议要具体：描述这张图应该展示什么主体、什么场景、什么风格，20-50字
- 每个配图位置的建议都要不同，贴合所在章节内容
- 注释放在对应章节标题的后一行，不影响大纲阅读
- 【禁止】输出"搜索关键词""画面描述""配图描述"等占位性文字

【示例】
### 核心原理一次讲透
<!-- 配图：宇宙深空全景，星系碰撞产生的绚丽光线，科幻风格，深蓝色调 -->

### 实战：从零搭建
<!-- 配图：工程师在服务器机房操作的场景，科技感，冷色调 -->
"""

        # 对大纲的额外要求（参考）
        extra_section = ""
        if extra_requirements and extra_requirements.strip():
            extra_section = f"""
用户对大纲的额外要求：{extra_requirements.strip()}
请在大纲结构中参考并体现这些要求。
"""

        prompt = f"""请以"{selected_title}"为标题，写一份博客文章大纲。

{style_section}
{research_section}
{image_section}
{extra_section}
【创作流程】
1. 先仔细思考：分析调研结果中的结构类型和推荐建议，结合文章风格，确定大纲的整体结构类型
2. 再制定大纲：严格按照确定的结构类型，制定各章节标题和内容说明

【重要】创作依据（必须严格遵守）：
- 文章风格必须严格遵守，大纲的结构类型、章节标题风格、内容深度都要符合该风格
- 章节结构必须认真参考调研结果中的大纲制定建议，不得凭空发挥或与同类文章结构雷同
- 必须严格执行：是否配图（如开启则标注配图注释）、用户对大纲的额外要求
- 已选标题"{selected_title}"是文章的唯一标题，大纲中不要重复输出这个标题

【大纲格式要求】
1. 章节标题风格：根据文章风格选择合适的标题风格，不要千篇一律
   - 科普/技术类：用吸引人的博客式小标题（如"为什么需要它？""核心原理一次讲透""实战：从零搭建"）
   - 论文类：用规范的学术标题（如"1. 引言""2. 相关工作""3. 方法设计"）
   - 散文类：用优美的文学化标题（如"初见""渐入佳境""余韵"）
   - 笔记类：用简洁的要点式标题（如"核心概念""关键步骤""注意事项"）
2. 结构建议（可根据文章风格灵活调整）：
   - 开头：引入主题，让读者知道为什么要读这篇
   - 主体：3-5个核心章节，循序渐进
   - 结尾：总结要点 + 延伸思考
3. 每个章节下面用1-2句话说明要写什么内容
4. 用 markdown 格式，## 表示大章节，### 表示小章节
5. 直接输出大纲，不要其他解释

请直接输出大纲："""
        outline = self.chat(prompt, temperature=0.7)

        # 配图标记质量保障：需要配图时，校验标记是否具体，无效则自动修复（最多2轮）
        if need_image:
            outline = self._ensure_valid_image_markers(outline)

        return outline

    # ============================================================
    # 配图标记校验与自动修复
    # ============================================================

    def _extract_image_markers(self, outline: str) -> List[str]:
        """提取大纲中所有配图注释的内容"""
        pattern = r'<!--\s*配图[：:]\s*(.+?)\s*-->'
        return [m.group(1).strip() for m in re.finditer(pattern, outline)]

    def _has_valid_image_markers(self, outline: str) -> bool:
        """校验配图标记：需要配图时，标记必须存在，且内容为具体描述（非占位词、长度≥3）"""
        markers = self._extract_image_markers(outline)
        if not markers:
            return False  # 需要配图但一个标记都没有，判无效
        for m in markers:
            if m in self.INVALID_IMAGE_MARKERS or len(m) < 3:
                return False
        return True

    def _fix_image_markers(self, outline: str) -> str:
        """让模型根据章节内容修复无效/缺失的配图注释（统一格式：配图内容建议）"""
        prompt = f"""以下是博客大纲，其中的配图注释存在问题：要么注释内容是占位文字（如"搜索关键词"），要么需要配图的章节缺少注释。

请修正大纲中的配图注释：
1. 保留注释的格式和位置：<!-- 配图：... -->
2. 有占位文字的注释，根据所在章节改成具体的配图内容建议（描述这张图应该展示什么主体、场景、风格，20-50字）
3. 明显需要配图（如对比、示意图、截图、步骤演示）但缺少注释的章节，补充注释
4. 只改动注释内容，其他大纲内容一字不改
5. 直接输出修正后的大纲，不要其他解释

大纲：
{outline}

修正后的大纲："""
        return self.chat(prompt, temperature=0.3)

    def _ensure_valid_image_markers(self, outline: str) -> str:
        """校验并修复配图标记，最多修复2轮；仍失败则原样返回，由配图阶段降级兜底"""
        for attempt in range(3):
            if self._has_valid_image_markers(outline):
                return outline
            print(f"[outliner] 配图标记校验未通过，第{attempt + 1}次自动修复...")
            outline = self._fix_image_markers(outline)
        print("[outliner] 配图标记修复2轮后仍未通过，保留现状，由配图阶段降级处理")
        return outline
