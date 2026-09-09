import json
from typing import Dict, Optional

from src.blog_agent.agent.agents.base_agent import BaseAgent


class ReviewerAgent(BaseAgent):
    """审稿 Agent：负责检查文章质量，给出修改意见"""

    name = "reviewer"
    role = "审稿编辑"
    system_prompt = """你是一个资深的技术博客审稿编辑，有10年以上技术内容审核经验。
你审稿时严格但不苛刻，重点关注文章的专业性、准确性和完整性，而不是吹毛求疵。

核心审稿原则：
1. 大纲遵从度：文章必须严格按照给定大纲的章节结构，不得擅自增删合并章节
2. 素材真实性：文章中引用的数据、版本号、案例必须来自调研素材，不得编造
3. 主旨紧扣度：每个章节都必须服务于文章主旨，不得跑题
4. 技术准确性：技术概念、代码示例、命令参数必须准确无误
5. 逻辑连贯性：章节之间要有递进关系，不能前后矛盾
6. 配图合理性：配图位置必须和大纲标记一致，图片内容要和上下文相关

合格标准：70分以上，没有严重问题即可通过。小问题写在建议里，不要反复修改。"""
    model_config_key = "llm_model_reviewer"

    def review_content(
        self,
        content: str,
        selected_title: str,
        outline: Optional[str] = None,
        content_research: Optional[str] = None,
    ) -> Dict:
        """
        专业审稿，返回结构化结果
        返回：{"passed": bool, "score": int, "issues": list, "suggestions": list, "feedback": str}
        """
        outline_section = ""
        if outline:
            outline_section = f"""
文章大纲（必须严格遵从的章节结构）：
{outline}
"""

        research_section = ""
        if content_research:
            research_section = f"""
写作前的调研素材（文章中的数据、版本号、案例应来自此处）：
{content_research}
"""

        prompt = f"""请以资深技术编辑的身份，专业审阅以下博客文章。

文章标题：{selected_title}
{outline_section}
{research_section}
文章内容：
{content}

请从以下7个维度专业审稿：

【维度1：大纲遵从度】（权重20%）
- 文章章节是否和大纲完全一致？有没有擅自增删、合并、重命名章节？
- 每个大纲中的章节是否都有对应的实质内容？
- 如果大纲中标注了配图位置，正文中是否保留了配图标记？

【维度2：素材真实性】（权重20%）
- 文章中的数据、版本号、技术名词是否和调研素材一致？
- 有没有编造不存在的数据、案例或引用？
- 有没有使用已经过时的技术信息？

【维度3：主旨紧扣度】（权重15%）
- 文章是否始终围绕标题和主旨展开？
- 有没有跑题、凑字数、无关内容？
- 每个章节是否都服务于主旨？

【维度4：技术准确性】（权重20%）
- 技术概念解释是否准确？
- 代码示例是否正确可运行？
- 命令、参数、配置是否有误？

【维度5：逻辑连贯性】（权重10%）
- 章节之间是否有递进关系？
- 有没有前后矛盾、跳跃过大？
- 论证是否充分？

【维度6：表达流畅度】（权重10%）
- 语言是否通顺？有没有明显错别字？
- 格式是否规范？markdown语法是否正确？

【维度7：配图合理性】（权重5%）
- 如果有配图标记，位置是否合理？
- 配图描述是否和上下文内容相关？

请严格按照以下JSON格式输出，不要输出其他内容：
{{
    "passed": true或false,
    "score": 0-100的整数评分,
    "dimension_scores": {{
        "outline": 0-100,
        "research": 0-100,
        "relevance": 0-100,
        "accuracy": 0-100,
        "logic": 0-100,
        "expression": 0-100,
        "image": 0-100
    }},
    "issues": ["严重问题1", "严重问题2", ...],
    "suggestions": ["改进建议1", "改进建议2", ...],
    "feedback": "总体评价，说明扣分原因和通过/不通过理由"
}}

审稿标准：
- 70分以上且没有严重问题 → 通过（passed=true）
- 以下情况必须不通过（passed=false）：
  * 擅自增删合并大纲章节（严重违反大纲遵从度）
  * 编造数据或使用严重过时的技术信息
  * 技术错误会误导读者
  * 内容空洞、跑题严重
- 小问题（个别错别字、表达可以更好）写在suggestions里，不影响通过
- issues只列严重问题，不要把小问题列进去
- feedback要具体，说明哪些维度扣分，为什么"""

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
                "issues": result.get("issues", []),
                "suggestions": result.get("suggestions", []),
                "feedback": result.get("feedback", ""),
            }
        except (json.JSONDecodeError, ValueError):
            return {
                "passed": False,
                "score": 0,
                "issues": ["审稿结果解析失败"],
                "suggestions": [],
                "feedback": resp[:500],
            }
