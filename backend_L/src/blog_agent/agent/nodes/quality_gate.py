"""
审稿质量门（主 Agent 把关，三个子图共用的模板）

职责：
1. 硬性约束的【代码级预计算】：标题一致性、字数、配图标记数量——
   这些不依赖 LLM 判断，由节点代码精确统计后拼进审稿任务指令
2. 调用 reviewer 模型精审（结构化输出 ReviewResult）
3. 打回机制：apply_feedback 节点把审稿意见/调研建议写回 state，
   review_router 条件边决定 放行 / 打回重跑 / 超限强制放行

state 约定：
- review_result: 最近一次评审结果（dict）
- review_count: 打回次数（apply_feedback 时 +1）
- max_review_rounds: 打回上限（settings 注入）
- review_feedback / research_suggestions: 给子 Agent 与调研段的指令
"""
import re
from typing import Any, Callable, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field

from src.blog_agent.agent.state import AgentState
from src.blog_agent.clients.llm_client import bind_structured_output

# ============================================================
# 结构化评审结果（与 REVIEW_CONTENT_TASK 的 JSON 格式一致）
# ============================================================

IMAGE_MARK_RE = re.compile(r"<!--\s*配图[：:]\s*")


class ReviewOpinion(BaseModel):
    """单条审稿意见：哪里需要改 / 为什么 / 期望改成什么样"""

    point: int
    where: str = Field(description="明确指出哪里需要改（具体到章节或段落）")
    why: str = Field(description="为什么需要改（违反了哪条标准）")
    expected: str = Field(description="期望改成什么样（具体的修改方向）")


class DimensionScores(BaseModel):
    """各维度评分（0-100）"""

    outline_compliance: int = Field(description="大纲符合度百分比，不低于80")
    relevance: int = Field(description="内容扣题度百分比，不低于80")
    style_match: int = Field(description="风格匹配度百分比，不低于75")
    research_usage: int = Field(description="调研素材引用程度百分比，不低于70")
    logic_flow: int = Field(description="逻辑流畅性分数（满分100），不低于85")


class ReviewResult(BaseModel):
    """审稿完整结果"""

    passed: bool
    score: int = Field(description="综合评分 0-100，不低于90才能通过")
    dimension_scores: DimensionScores
    review_opinions: List[ReviewOpinion] = Field(
        default_factory=list, description="审核不通过时必填，逐条列出；通过时为空数组"
    )
    pass_reasons: List[str] = Field(
        default_factory=list, description="审核通过时必填，分点列出通过理由"
    )
    need_re_research: bool = Field(
        default=False, description="是否需要重新调研（缺少关键数据/案例/事实错误）"
    )
    research_type: str = Field(
        default="", description='"重新调研" 或 "补充调研" 或 空'
    )
    research_list: List[str] = Field(
        default_factory=list, description="需要调研时的方向列表（含搜索关键词建议）"
    )
    traffic_forecast: str = Field(
        default="", description='"一般/中等/高/火/爆火"，审核通过时给出'
    )


class TitleReviewResult(BaseModel):
    """标题质量门结果（主 Agent 评审候选标题，supervisor_graph 用）"""

    passed: bool
    score: int = Field(description="综合评分 0-100，不低于85才能通过")
    relevance: int = Field(description="与主题相关度百分比，不低于80")
    type_match: int = Field(description="与调研判断的文章类型匹配度百分比，不低于75")
    attractiveness: int = Field(description="吸引力与差异化程度（0-100），不低于75")
    review_opinions: List[ReviewOpinion] = Field(
        default_factory=list, description="不通过时必填，逐条列出；通过时为空数组"
    )
    pass_reasons: List[str] = Field(
        default_factory=list, description="通过时必填，分点列出通过理由"
    )


class OutlineReviewResult(BaseModel):
    """大纲质量门结果（主 Agent 评审大纲，supervisor_graph 用）"""

    passed: bool
    score: int = Field(description="综合评分 0-100，不低于85才能通过")
    structure_match: int = Field(description="结构符合度百分比（与文章风格匹配），不低于80")
    research_reference: int = Field(description="调研参考度百分比（避免与同类文章雷同），不低于70")
    completeness: int = Field(description="完整度百分比（引入/主体/总结+章节说明），不低于75")
    image_marks: int = Field(description="配图标记合格度百分比（无需配图时给100），不低于70")
    review_opinions: List[ReviewOpinion] = Field(
        default_factory=list, description="不通过时必填，逐条列出；通过时为空数组"
    )
    pass_reasons: List[str] = Field(
        default_factory=list, description="通过时必填，分点列出通过理由"
    )


# ============================================================
# 硬性约束 · 代码级预计算（不依赖 LLM 的确定性统计）
# ============================================================


def count_image_marks(text: str) -> int:
    """统计正文/大纲中的配图标记数量（<!-- 配图：... -->）"""
    if not text:
        return 0
    return len(IMAGE_MARK_RE.findall(text))


def count_chars(text: str) -> int:
    """字数统计：去除空白字符后的字符数（作为"实际字数"的估算口径）"""
    if not text:
        return 0
    return len(re.sub(r"\s", "", text))


def title_preserved(selected_title: str, content: str) -> bool:
    """标题一致性：正文中必须原样包含用户选择的标题（一字不差）"""
    if not selected_title:
        return True  # 无标题要求时不校验
    return selected_title.strip() in (content or "")


# ============================================================
# 审稿节点工厂
# ============================================================


def make_quality_gate_node(
    review_system: str,
    task_builder: Callable[[AgentState], str],
    result_schema: Type[BaseModel] = ReviewResult,
    model_role: str = "reviewer",
    enable_thinking: Optional[bool] = None,
):
    """
    生成一个审稿质量门节点。

    - review_system: 审稿人设（REVIEW_CONTENT_SYSTEM 等）
    - task_builder: 根据 state 拼审稿任务指令（含硬性约束预计算值）
    - result_schema: 结构化输出模型（默认 ReviewResult）
    - enable_thinking: None 按角色白名单；True/False 强制覆盖（如标题门关思考提速）
    """
    model = bind_structured_output(
        result_schema, role=model_role, enable_thinking=enable_thinking
    )

    def quality_gate_node(state: AgentState) -> Dict[str, Any]:
        task = task_builder(state)
        obj = model.invoke(task)
        return {"review_result": obj.model_dump()}

    return quality_gate_node


# ============================================================
# 打回反馈节点 + 路由
# ============================================================


def format_review_opinions(review: Dict[str, Any]) -> str:
    """把 review_opinions 转成给子 Agent 的逐条指令文本"""
    opinions = review.get("review_opinions") or []
    if not opinions:
        return ""
    lines = [
        f"{i + 1}. 【哪里】{o.get('where')}；【为什么】{o.get('why')}；"
        f"【期望】{o.get('expected')}"
        for i, o in enumerate(opinions)
    ]
    return "\n".join(lines)


def format_research_suggestions(review: Dict[str, Any]) -> str:
    """把 need_re_research / research_type / research_list 转成调研指令文本"""
    if not review.get("need_re_research"):
        return ""
    research_list = review.get("research_list") or []
    lines = "\n".join(f"- {item}" for item in research_list)
    return (
        f"审稿判定需要{review.get('research_type', '补充调研')}，调研方向如下：\n{lines}"
    )


def make_apply_feedback_node():
    """
    打回准备节点：记录打回次数，把审稿意见与调研建议写入 state，
    供子 Agent 重跑时携带（review_feedback / research_suggestions）。
    """

    def apply_feedback_node(state: AgentState) -> Dict[str, Any]:
        review: Dict[str, Any] = state.get("review_result") or {}
        return {
            "review_count": state.get("review_count", 0) + 1,
            "review_feedback": format_review_opinions(review),
            "research_suggestions": format_research_suggestions(review),
        }

    return apply_feedback_node


def review_router(state: AgentState) -> Literal["pass", "retry", "force_pass"]:
    """
    质量门条件边：
    - 评审通过 -> pass（放行进入下一阶段）
    - 未通过且打回次数未达上限 -> retry（回到子图重跑）
    - 未通过且已达上限 -> force_pass（强制放行，避免死循环）
    """
    review: Dict[str, Any] = state.get("review_result") or {}
    if review.get("passed"):
        return "pass"
    if state.get("review_count", 0) < state.get("max_review_rounds", 3):
        return "retry"
    return "force_pass"
