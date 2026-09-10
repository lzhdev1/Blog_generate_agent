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
                image_desc = """在需要配图的章节前，用HTML注释标注配图位置和具体的图片搜索关键词。

【格式要求】
- 注释格式：<!-- 配图：<具体搜索关键词> -->
- 关键词要具体，可直接拿去图片网站搜索（如"红树林生态分布对比图""服务器机房实拍""代码运行截图"），限2-15个字
- 每个配图位置的注释内容都要不同，贴合所在章节内容
- 【禁止】输出"搜索关键词""画面描述"等占位性文字

【示例】
### 核心原理一次讲透
<!-- 配图：神经元突触连接示意图 -->

### 实战：从零搭建
<!-- 配图：Docker容器部署架构图 -->"""
            else:
                image_desc = """在需要配图的章节前，用HTML注释标注配图位置和画面描述。

【格式要求】
- 注释格式：<!-- 配图：<画面描述> -->
- 画面描述要具体：主体、场景、风格、色调，20-50字
- 每个配图位置的描述都要不同，贴合所在章节内容
- 【禁止】输出"搜索关键词""画面描述"等占位性文字

【示例】
### 核心原理一次讲透
<!-- 配图：实验室风格对比图，左侧显示传统集中刷题导致的疲劳皱眉，右侧显示间隔复习时的专注状态 -->"""
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
        outline = self.chat(prompt, temperature=0.7)

        # 配图标记质量保障：需要配图时，校验标记是否具体，无效则自动修复（最多2轮）
        if need_image:
            outline = self._ensure_valid_image_markers(outline, image_source)

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

    def _fix_image_markers(self, outline: str, image_source: str) -> str:
        """让模型根据章节内容修复无效/缺失的配图注释"""
        if image_source == "api":
            target = '具体的图片搜索关键词（2-15个字，能直接在图片网站搜到，如"红树林生态分布对比图"）'
        else:
            target = "具体的画面描述（主体+场景+风格，20-50字）"
        prompt = f"""以下是博客大纲，其中的配图注释存在问题：要么注释内容是占位文字（如"搜索关键词"），要么需要配图的章节缺少注释。

请修正大纲中的配图注释：
1. 保留注释的格式和位置：<!-- 配图：... -->
2. 有占位文字的注释，根据所在章节改成{target}
3. 明显需要配图（如对比、示意图、截图、步骤演示）但缺少注释的章节，补充注释
4. 只改动注释内容，其他大纲内容一字不改
5. 直接输出修正后的大纲，不要其他解释

大纲：
{outline}

修正后的大纲："""
        return self.chat(prompt, temperature=0.3)

    def _ensure_valid_image_markers(self, outline: str, image_source: str) -> str:
        """校验并修复配图标记，最多修复2轮；仍失败则原样返回，由配图阶段降级兜底"""
        for attempt in range(3):
            if self._has_valid_image_markers(outline):
                return outline
            print(f"[outliner] 配图标记校验未通过，第{attempt + 1}次自动修复...")
            outline = self._fix_image_markers(outline, image_source)
        print("[outliner] 配图标记修复2轮后仍未通过，保留现状，由配图阶段降级处理")
        return outline
