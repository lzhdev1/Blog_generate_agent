import json
from typing import Dict, Optional

from src.blog_agent.agent.agents.base_agent import BaseAgent


class ReviewerAgent(BaseAgent):
    """审稿 Agent：负责检查文章质量，给出修改意见"""

    name = "reviewer"
    role = "审稿编辑"
    system_prompt = """你是一个资深的文章审稿编辑，有10年以上内容审核经验，擅长各类文章（技术科普、行业分析、生活随笔、财经解读、情感随笔等）的质量评估。
你审稿时严格但不苛刻，重点关注文章的专业性、准确性和完整性，而不是吹毛求疵。

核心审稿原则：
1. 大纲遵从度：文章必须严格按照给定大纲的章节结构，不得擅自增删合并章节
2. 素材真实性：文章中引用的数据、案例、来源必须来自调研素材，不得编造
3. 主旨紧扣度：每个章节都必须服务于文章主旨，不得跑题
4. 内容准确性：文中的概念、数据、事实必须准确无误（根据文章类型调整审核重点：技术类看技术准确性，财经类看数据准确性，生活类看常识准确性）
5. 逻辑连贯性：章节之间要有递进关系，不能前后矛盾
6. 表达流畅度：语言通顺，格式规范
7. 配图合理性：配图位置必须和大纲标记一致，图片内容要和上下文相关

合格标准：80分以上，没有严重问题即可通过。小问题写在建议里，不要反复修改。"""
    model_config_key = "llm_model_reviewer"

    def review_content(
        self,
        content: str,
        selected_title: str,
        outline: Optional[str] = None,
        content_research: Optional[str] = None,
        article_style: Optional[str] = None,
        article_style_custom: Optional[str] = None,
        word_count: Optional[int] = None,
    ) -> Dict:
        """
        专业审稿，返回结构化结果
        article_style: 用户选择的文章风格
        word_count: 用户配置的目标字数
        """
        import re as _re

        # 预计算：实际字数（去除markdown标记和配图注释）
        content_clean = _re.sub(r'<!--\s*配图[：:].*?-->', '', content)
        content_clean = _re.sub(r'[#*>`\-\[\]\(\)!]', '', content_clean)
        content_clean = _re.sub(r'\s+', '', content_clean)
        actual_word_count = len(content_clean)

        # 预计算：正文中的配图标记数量
        actual_image_count = len(_re.findall(r'<!--\s*配图[：:]', content))

        # 预计算：大纲中的配图标记数量
        required_image_count = 0
        if outline:
            required_image_count = len(_re.findall(r'<!--\s*配图[：:]', outline))

        # 文章风格描述
        style_map = {
            "popular_science": "科普类（通俗易懂，面向大众读者）",
            "technical": "技术类（有技术深度，面向有基础的读者）",
            "essay": "论文类（学术严谨，论证严密）",
            "prose": "散文类（文笔优美，抒情叙事）",
            "note": "笔记类（简洁实用，要点清晰）",
        }
        style_desc = style_map.get(article_style, "")
        if article_style == "custom" and article_style_custom:
            style_desc = f"自定义风格：{article_style_custom}"

        outline_section = ""
        if outline:
            outline_section = f"""
文章大纲（必须严格遵从的章节结构）：
{outline}
"""

        research_section = ""
        if content_research:
            if len(content_research) > 8000:
                content_research = content_research[:8000] + "\n...（调研内容过长，已截断）"
            research_section = f"""
写作前的调研素材（文章中的数据、案例应来自此处）：
{content_research}
"""

        style_section = ""
        if style_desc:
            style_section = f"""
用户选择的文章风格：{style_desc}
"""

        word_count_section = ""
        if word_count:
            word_count_section = f"""
目标字数：{word_count}字（允许超出200字以内，不允许少于目标字数）
实际字数：{actual_word_count}字
"""

        image_count_section = ""
        if required_image_count > 0:
            image_count_section = f"""
大纲中标记的配图数量：{required_image_count}张（一张都不能少）
正文中实际保留的配图标记数量：{actual_image_count}张
"""

        prompt = f"""请以资深文章编辑的身份，严格审阅以下博客文章。

文章标题：{selected_title}
{style_section}
{word_count_section}
{image_count_section}
{outline_section}
{research_section}
文章内容：
{content}

【审核标准（必须严格执行）】

一、硬性约束（违反任何一条直接不通过）：
1. 标题一个字都不能错：正文不得擅自修改、替换或缩写用户选择的标题"{selected_title}"
2. 字数只允许多不允许少：实际字数不得少于目标字数，超出目标字数200字以内是允许的
3. 配图一张都不能少：如果大纲中标记了配图位置，正文中必须保留相同数量的配图标记

二、各项审核（百分比或分数评价，不得低于对应阈值）：
1. 大纲符合程度：百分比评价，不得低于80%。检查章节标题、层级、顺序是否与大纲一致，每个章节是否有实质内容
2. 内容扣题程度：百分比评价，不得低于80%。检查是否始终围绕标题和主旨展开，有没有跑题、凑字数、无关内容
3. 风格匹配度：百分比评价，不得低于75%。检查全文风格是否和用户选择的文章风格匹配（用词、深度、语气等）
4. 调研素材引用程度：百分比评价，不得低于70%。检查文章中的数据、案例、事实是否引用了调研素材，有没有编造不存在的内容
5. 逻辑流畅性：分数评价（满分100），不得低于85分。检查章节间的递进关系、前后是否矛盾、论证是否充分、语言是否通顺

（说明：配图符合度不在审稿范围内，因为审稿时图片尚未生成，配图质量由配图agent自行保障）

三、综合评价：
- 综合评分满分100，不得低于90分才能通过
- 不能胡乱给高分，必须根据上述各项审核结果客观评分
- 硬性约束违反直接不通过，综合评分不得高于70

【输出要求】

请严格按照以下JSON格式输出，不要输出其他内容：
{{
    "passed": true或false,
    "score": 0-100的整数（综合评分）,
    "hard_constraints": {{
        "title_correct": true或false,
        "word_count_ok": true或false,
        "word_count_actual": {actual_word_count},
        "word_count_target": {word_count if word_count else 0},
        "image_count_ok": true或false,
        "image_count_actual": {actual_image_count},
        "image_count_required": {required_image_count}
    }},
    "dimension_scores": {{
        "outline_compliance": 0-100（大纲符合度百分比）,
        "relevance": 0-100（内容扣题度百分比）,
        "style_match": 0-100（风格匹配度百分比）,
        "research_usage": 0-100（调研素材引用程度百分比）,
        "logic_flow": 0-100（逻辑流畅性分数）
    }},
    "review_opinions": [
        {{
            "point": 1,
            "where": "明确指出哪里需要改（具体到章节或段落）",
            "why": "为什么需要改（违反了哪条标准）",
            "expected": "期望改成什么样（具体的修改方向）"
        }}
    ],
    "pass_reasons": ["通过理由1", "通过理由2"],
    "need_re_research": true或false,
    "research_type": "重新调研"或"补充调研"或空字符串,
    "research_list": ["调研方向1（含搜索关键词建议）", "调研方向2"],
    "traffic_forecast": "一般"或"中等"或"高"或"火"或"爆火"
}}

【填写说明】
- review_opinions：审核不通过时必填，列出1.2.3...点，每点必须包含where/why/expected三个字段；审核通过时填空数组
- pass_reasons：审核通过时必填，分点列出通过的理由；审核不通过时填空数组
- need_re_research：判断是否需要重新调研。如果文章内容缺少关键数据、案例或事实错误，需要调研补充，则为true
- research_type：如果需要调研，明确是"重新调研"（现有调研完全不够，需要全部重做）还是"补充调研"（现有调研部分可用，需要补充某些方向）
- research_list：需要调研时必填，给出详细的调研方向列表，每个方向包含需要搜索什么、建议关键词
- traffic_forecast：审核通过时给出流量预期；审核不通过时填空字符串
- 硬性约束检查结果必须如实填写，title_correct/word_count_ok/image_count_ok 是预计算值的判断结果"""

        resp = self.chat(prompt, temperature=0.3)

        # 解析 JSON 结果
        try:
            resp_clean = resp.strip()
            if resp_clean.startswith("```"):
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
                "hard_constraints": result.get("hard_constraints", {}),
                "dimension_scores": result.get("dimension_scores", {}),
                "review_opinions": result.get("review_opinions", []),
                "pass_reasons": result.get("pass_reasons", []),
                "need_re_research": bool(result.get("need_re_research", False)),
                "research_type": result.get("research_type", ""),
                "research_list": result.get("research_list", []),
                "traffic_forecast": result.get("traffic_forecast", ""),
            }
        except (json.JSONDecodeError, ValueError):
            return {
                "passed": False,
                "score": 0,
                "hard_constraints": {},
                "dimension_scores": {},
                "review_opinions": [{"point": 1, "where": "审稿结果解析失败", "why": "LLM输出格式错误", "expected": "请重试"}],
                "pass_reasons": [],
                "need_re_research": False,
                "research_type": "",
                "research_list": [],
                "traffic_forecast": "",
            }
