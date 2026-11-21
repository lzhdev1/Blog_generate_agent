"""
审稿质量门（主 Agent 把关，三个子图共用的模板）

职责：
1. 硬性约束的【代码级预计算】：标题一致性、字数、配图标记数量——
   这些不依赖 LLM 判断，由节点代码精确统计后拼进审稿任务指令
2. 调用 reviewer 模型精审（结构化输出 ReviewResult）
3. 打回机制：apply_feedback 节点把审稿意见/调研建议写回 state，
   review_router 条件边决定 放行 / 打回重跑 / 超限停止

state 约定：
- review_result: 最近一次评审结果（dict）
- review_count: 打回次数（apply_feedback 时 +1）
- max_review_rounds: 打回上限（settings 注入）
- review_feedback / research_suggestions: 给子 Agent 与调研段的指令
"""
import re
from itertools import groupby
from typing import Annotated, Any, Callable, Dict, List, Literal, Optional, Type

from langchain_core.exceptions import OutputParserException
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from config.settings import settings
from src.blog_agent.agent.agents.prompt_utils import IMAGE_MARKER_RE, editorial_brief, word_count_bounds
from src.blog_agent.agent.agents.personal_note import unsupported_personal_effects, unsupported_personal_history
from src.blog_agent.agent.evidence import asserted_observations, can_recheck_existing_numbers, cited_sources, evidence_issues, indexed_sentences, requires_sources, unsupported_outline_measurements
from src.blog_agent.agent.nodes.output_node import collect_search_results
from src.blog_agent.agent.agents.short_brief import short_brief
from src.blog_agent.agent.nodes.tutorial_check import tutorial_input_issues
from src.blog_agent.agent.state import AgentState
from src.blog_agent.clients.llm_client import bind_structured_output

# ============================================================
# 结构化评审结果（与 REVIEW_CONTENT_TASK 的 JSON 格式一致）
# ============================================================

EDITORIAL_POLICY_VERSION = 1
Score = Annotated[int, Field(ge=0, le=100)]
NonemptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ReviewOpinion(BaseModel):
    """单条审稿意见：哪里需要改 / 为什么 / 期望改成什么样"""

    point: int
    where: NonemptyText = Field(description="明确指出哪里需要改（具体到章节或段落）")
    why: NonemptyText = Field(description="为什么需要改（违反了哪条标准）")
    expected: NonemptyText = Field(description="期望改成什么样（具体的修改方向）")


class DimensionScores(BaseModel):
    """各维度评分（0-100）"""

    outline_compliance: Score = Field(description="大纲符合度百分比，不低于80")
    relevance: Score = Field(description="内容扣题度百分比，不低于80")
    style_match: Score = Field(description="风格匹配度百分比，不低于75")
    research_usage: Score = Field(description="外部事实的资料支持度，纯表达性文体按本次要求评估")
    logic_flow: Score = Field(description="逻辑流畅性分数（满分100），不低于85")


class ClaimCheck(BaseModel):
    item: int = Field(ge=1, description="程序在逐项核验清单中给出的序号")
    basis: NonemptyText = Field(description="来源编号如 S1、作者、表达或无据")
    quote: NonemptyText = Field(description="来源或作者输入中的连续短原文；表达或无据时摘取稿中相应短语")


class ReviewResult(BaseModel):
    """审稿完整结果"""

    passed: bool
    score: Score = Field(description="综合评分 0-100，放行门槛见本次任务")
    dimension_scores: DimensionScores
    claim_checks: List[ClaimCheck] = Field(default_factory=list, description="逐项核验清单的依据，每个序号一项")
    review_opinions: List[ReviewOpinion] = Field(
        default_factory=list, description="审核不通过时必填，逐条列出；通过时为空数组"
    )
    pass_reasons: List[NonemptyText] = Field(
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


class TitleReviewResult(BaseModel):
    """标题质量门结果（主 Agent 评审候选标题，supervisor_graph 用）"""

    passed: bool
    score: Score = Field(description="综合评分 0-100，不低于85才能通过")
    relevance: Score = Field(description="与主题相关度百分比，不低于80")
    type_match: Score = Field(description="与调研判断的文章类型匹配度百分比，不低于75")
    attractiveness: Score = Field(description="吸引力与差异化程度（0-100），不低于75")
    review_opinions: List[ReviewOpinion] = Field(
        default_factory=list, description="不通过时必填，逐条列出；通过时为空数组"
    )
    pass_reasons: List[NonemptyText] = Field(
        default_factory=list, description="通过时必填，分点列出通过理由"
    )


class SingleTitleReviewResult(TitleReviewResult):
    selected_title: str = Field(description="独立审核通过的候选标题原文；没有合格标题时填空字符串")


class ShortOutlineReview(BaseModel):
    coverage: NonemptyText = Field(description="用原始选题和具体章节名称解释每个问题是否有对应章节")
    blocking_issues: list[ReviewOpinion] = Field(description="只填需要作者调整才能动笔的实质缺陷。没有缺陷时返回空数组。")


class OutlineReviewResult(BaseModel):
    """大纲质量门结果（主 Agent 评审大纲，supervisor_graph 用）"""

    passed: bool
    score: Score = Field(description="综合评分 0-100，不低于85才能通过")
    structure_match: Score = Field(description="结构符合度百分比（与文章风格匹配），不低于80")
    research_reference: Score = Field(description="调研参考度百分比（避免与同类文章雷同），不低于70")
    completeness: Score = Field(description="完整度百分比（引入/主体/总结+章节说明），不低于75")
    image_marks: Score = Field(description="配图标记合格度百分比（无需配图时给100），不低于70")
    review_opinions: List[ReviewOpinion] = Field(
        default_factory=list, description="不通过时必填，逐条列出；通过时为空数组"
    )
    pass_reasons: List[NonemptyText] = Field(
        default_factory=list, description="通过时必填，分点列出通过理由"
    )


# ============================================================
# 硬性约束 · 代码级预计算（不依赖 LLM 的确定性统计）
# ============================================================


def count_image_marks(text: str) -> int:
    """统计正文/大纲中的配图标记数量（<!-- 配图：... -->）"""
    if not text:
        return 0
    return len(IMAGE_MARKER_RE.findall(text))


def _markdown_lines(text: str):
    """Classify Markdown lines so examples are counted as code, never as prose or headings."""
    fence = ""
    for line in (text or "").splitlines():
        if fence:
            if re.fullmatch(r" {0,3}" + fence[0] + "{" + str(len(fence)) + r",}[ \t]*", line):
                fence = ""
            else:
                yield "code", line
        elif opening := re.match(r"^ {0,3}(`{3,}|~{3,})", line):
            fence = opening[1]
        else:
            yield "prose", line


def count_chars(text: str, *, exclude_headings: bool = False) -> int:
    """同一计量口径用于生成和修订：正文与代码计入；插图、引用编号、链接目标和排版符号不计。"""
    total = 0
    for kind, group in groupby(_markdown_lines(text), key=lambda item: item[0]):
        section = "\n".join(line for _, line in group)
        if kind == "prose":
            if exclude_headings:
                section = re.sub(r"(?m)^ {0,3}#{1,6}[ \t]+.*$", "", section)
            section = re.sub(r"<!--.*?-->|<img\b[^>]*>", "", section, flags=re.S | re.I)
            section = re.sub(r"(?m)^ {0,3}\[[^\[\]\n]+\]:[ \t]+\S.*$", "", section)
            # Generated local images and inline Markdown links. Parenthesized URL path segments
            # and optional titles are common in author-supplied links.
            section = re.sub(r"(!?)\[([^\[\]\n]*)\]\((?:[^()\n]|\([^()\n]*\))*\)",
                             lambda m: "" if m[1] else m[2], section)
            section = re.sub(r"!\[[^\]\n]*\]\[[^\]\n]*\]|\[S\d+\]", "", section, flags=re.I)
            section = re.sub(r"(?m)^ {0,3}(?:#{1,6}|[-*+>]|\d+[.、．)])\s+", "", section)
            section = re.sub(r"(\*\*|__|~~|`)([^\n]+?)\1", r"\2", section)
        total += len(re.sub(r"\s", "", section))
    return total


def title_preserved(selected_title: str, content: str) -> bool:
    """标题一致性：正文中必须原样包含用户选择的标题（一字不差）"""
    if not selected_title:
        return True  # 无标题要求时不校验
    first_line = (content or "").strip().partition("\n")[0].strip()
    return re.fullmatch(r"#\s+" + re.escape(selected_title.strip()), first_line) is not None


def _section_headings(text: str) -> list[tuple[str, str]]:
    headings = []
    for kind, line in _markdown_lines(text):
        if kind == "prose" and (match := re.match(r"^ {0,3}(#{2,3})\s+(.+)$", line)):
            headings.append((match[1], re.sub(r"\s+#+$", "", match[2].strip())))
    return headings


def minimum_body_score(state: AgentState) -> int:
    """短稿特例只适用于目标不超过500字且按原大纲完整组织的文章。"""
    target = state.get("word_count") or 800
    expected = _section_headings(state.get("outline") or "")
    if target <= 500 and expected and expected == _section_headings(state.get("content") or ""):
        return 85
    return 90


def grade_research_usage(state: AgentState) -> bool:
    return requires_sources(state) or bool(cited_sources(state.get("content") or "", state.get("evidence_sources") or []))


_SCOPE = re.compile(
    r"始终|总是|一律|任何|永远|必然|必定|所有|大多数|多数时候|通常|偶尔|只有|只要|零误差|完全|杜绝|"
    r"绝[无不]|每(?:个|逢|次|天|日|月|周|年|晚|一)|从不|只(?:能|可能)|"
    r"\b(?:always|never|every|only|usually|most|inevitably)\b", re.I)
_CAUSAL = re.compile(r"根源|导致|引发|使得|从而|归因于|有助于|缓解|治愈|疗效|有效提升|实验证明|"
                     r"研究(?:表明|发现|显示)|\b(?:causes?|prevents?|cures?)\b", re.I)
_OBSERVATION = re.compile(r"当时|昨[天日晚夜]|那[天晚年时]|曾经|[晨昼夜晚]|看见|听见|"
                          r"光[线晕]|摆[着放]|[拿摸听贴摆压敲站坐隔放走]着|身[旁边]|面前|了")
_EXACT_ALIGNMENT = re.compile(r"(?:严格|精确|精准|分毫不差地?|完美)(?:地)?(?:共线|对齐|重合|排成一条直线)")
_EXACT_SOURCE = re.compile(r"(?:严格|精确|精准|完美).{0,9}(?:共线|对齐|重合|直线)|"
                           r"\b(?:exact(?:ly)?|perfect(?:ly)?|precise(?:ly)?|strict(?:ly)?)\s+"
                           r"(?:collinear|alignment|aligned|overlap|(?:in\s+)?a\s+straight\s+line)\b", re.I)


def _demands_exact_alignment(claim):
    for match in _EXACT_ALIGNMENT.finditer(claim):
        before = claim[:match.start()]
        if re.search(r"(?:不必|无需|不需(?:要)?|不要求|不一定(?:要)?|未必(?:要)?|不是必须|不意味着).{0,5}$", before):
            continue
        if re.search(r"(?:未(?:能)?|没有|并不|不)$", before) and not re.search(r"无法|不能|就不会|不可能", claim[match.end():]):
            continue
        return True
    return False
# A source stating a negative frequency cannot support a positive calendar guarantee.
_FREQUENCIES = [
    (re.compile(claim, re.I), re.compile(evidence, re.I))
    for claim, evidence in (
        (r"每(?:一?个)?月(?:份)?(?:都|必|总)|every (?:calendar )?month",
         r"每(?:一?个)?月|按月|逐月|monthly|(?:every|each|per|once a) (?:calendar )?month"),
        (r"每(?:一天|天|日)(?:都|必|总)|every day", r"每日|每天|逐日|daily|(?:every|each|per|once a) day"),
        (r"每(?:一?个)?周(?:都|必|总)|every week", r"每(?:一?个)?周|逐周|weekly|(?:every|each|per|once a) week"),
        (r"每(?:一)?年(?:都|必|总)|every year", r"每(?:一)?年|逐年|annual|yearly|(?:each|every|per|once a) year"),
        (r"大多数时候|多数时候|most of the time", r"通常|一般|大多|多数|往往|常常|usually|generally|typical|often|most"),
    )
]
_NEGATIVE_FREQUENCY = re.compile(r"(?:instead of|rather than|not (?!only |just )|并非|而非|并不|不是)[^。.!?；;，,]*", re.I)


_ABSOLUTE = r"(?<!不)(?<!非)(?<!未)(?:总是|总在|总会|必定|必然|无一例外)"
_ABSOLUTE_QUESTION = re.compile(r"(?:为什么|为何|为啥)[^，。？！?！!；;]{0,55}?" + _ABSOLUTE)
_DISPUTED_PREMISE = re.compile(r"(?:是|属于)(?:一[个种条])?(?:误解|谬误|误区|错误)|(?:并不|不能)成立|这个说法错")
_WELLBEING_TOPIC = re.compile(r"心理|情绪|失眠|焦虑|抑郁|反刍|压力|认知(?:负荷|卸载)|疗愈|疗效|治疗|治愈|大脑.{0,8}卸载")
_INTERVENTION = re.compile(r"(?:缓解|解除|治好|克服|拒绝|摆脱|告别|治愈|赶走|改善|战胜).{0,8}(?:焦虑|抑郁|反刍|失眠)|"
                           r"(?:大脑|认知).{0,8}卸载|心理疗效|治愈力")


def _planning_scope_issues(state, headings):
    brief = "\n".join(state.get(key) or "" for key in ("topic", "purpose", "extra_requirements", "content_extra_requirements"))
    personal = state.get("article_style") in {"note", "prose"}
    for heading in headings:
        if (not personal and requires_sources(state) and _ABSOLUTE_QUESTION.search(heading)
                and not re.search(_ABSOLUTE, brief) and not _DISPUTED_PREMISE.search(heading)):
            yield ("选题范围", f"“{heading}”预设现象必然发生，原始题目没有这项前提", "改成可由正文回答的开放问题，或交代发生条件")
        if personal and _INTERVENTION.search(heading) and not _WELLBEING_TOPIC.search(brief):
            yield ("创作意图", f"“{heading}”把个人笔记扩展成了心理干预，超出作者简报", "围绕给定的小事、个人取舍或打算拟题")


def _frequency_supported(claim, excerpt):
    assertion = _NEGATIVE_FREQUENCY.sub("", claim)
    affirmative = _NEGATIVE_FREQUENCY.sub("", excerpt)
    return all(not marker.search(assertion) or equivalent.search(affirmative)
               for marker, equivalent in _FREQUENCIES)


def _claims_to_check(state):
    """Bound same-call checks, prioritising scope and observable details over rhetoric."""
    if not state.get("topic"):
        return []
    personal = state.get("article_style") in {"note", "prose"}
    factual = requires_sources(state)
    candidates = {}
    for kind, line in _markdown_lines(state.get("content") or ""):
        if kind != "prose" or line.lstrip().startswith(("#", "<!--", "[S")):
            continue
        for phrase in re.split(r"(?<=[。！？!?])|(?<=\.)\s+|[；;]|[，,]\s*(?=但|而(?:非|是)|却|however\b|but\b)", line):
            phrase = phrase.strip()
            if not phrase or phrase.endswith(("?", "？")):
                continue
            if personal:
                phrase = asserted_observations(phrase).strip(" ，,")
                if not phrase:
                    continue
            priority = (4 * bool(personal and unsupported_personal_effects(state, phrase)) + 2 * bool(_SCOPE.search(phrase)) + 2 * bool(_CAUSAL.search(phrase))
                        + (bool(_OBSERVATION.search(phrase)) if personal else 0))
            if factual and re.search(r"\[S\d+\]", phrase, re.I):
                priority += 1
            if _demands_exact_alignment(phrase):
                priority += 5
            if any(marker.search(phrase) for marker, _ in _FREQUENCIES):
                priority += 2
            if priority or personal:
                candidates[phrase] = priority
    selected = set(sorted(candidates, key=candidates.get, reverse=True)[:6])
    return [phrase for phrase in candidates if phrase in selected]


def _claim_check_prompt(claims):
    if not claims:
        return ""
    return ("\n【发布前逐项核验】对下列每个编号检查整句，包括顺带加入的环境、时刻、限定或因果。"
            "在 claim_checks 中逐项回报。basis 填支持这句的 S 编号或“作者”，quote 须从该来源摘录或作者原始输入逐字摘取最直接的依据。"
            "引文须支持同一对象的同一频率和方向；先核对主语、谓语、时间单位。相邻分句的成立条件不能互相代替，"
            "否定某事按周期发生的摘录不能证明另一件事必然按期发生。"
            "个人偏好与具体取舍可以作为表达。凡涉及心理、生理、记忆或群体的效果，须检查独立资料，第一人称并不能证明这些效果。授权虚构仍要遵守同一简报的限制。词义相当、自然蕴含可接受；材料没有交代的具体光线、时间、地点及事件不能凭常识填入。"
            "仅主观取舍、明确假设、比喻、否认有证据或明确授权的自由创作，填“表达”，摘录该措辞。"
            "句中只要有一项具体事实超出依据，填“无据”，摘出越界的原词，判退并指出应改之处。每项仅摘最短的一处原文，禁用省略号拼接。\n"
            "对网页依据，quote 优先填写最直接支持这句话的原句地址（例如 @S3.2），系统会取回该页的真实原句。"
            "原句支持的主体、关系、限定须完全对应，否则填无据。\n"
            + "\n".join(f"{i}. {claim}" for i, claim in enumerate(claims, 1)))


def _claim_check_issues(report, state, claims):
    checks = report.claim_checks
    if sorted(check.item for check in checks) != list(range(1, len(claims) + 1)):
        return ["逐项核验编号缺失、重复或超出清单"]
    sources = {src["id"]: src.get("excerpt", "") for src in state.get("evidence_sources") or []}
    author_inputs = [state.get(field) or "" for field in
                     ("topic", "purpose", "article_style_custom", "extra_requirements", "content_extra_requirements")]
    issues = []
    for check in checks:
        claim = claims[check.item - 1]
        basis = check.basis.strip("[]")
        if re.fullmatch(r"s\d+", basis, re.I):
            basis = basis.upper()
        if basis == "无据":
            issues.append(f"“{claim}”中的“{check.quote}”缺乏依据")
            continue
        if basis == "作者":
            records = author_inputs
        elif basis == "表达":
            records = [claim]
            expression = re.search(r"假[设如]|想象|比作|好比|仿佛|比如|例如|以.+为例|我(?:觉得|希望|想|不敢断言|无法断定)", claim)
            if state.get("article_style") in {"note", "prose"} and not requires_sources(state):
                expression = expression or re.search(r"我(?:打算|计划|宁愿|愿意|担心|设想|还不确定)", claim)
            if unsupported_personal_effects(state, claim) or ((requires_sources(state) or _CAUSAL.search(claim)) and not expression):
                issues.append(f"事实型稿件的限定句“{claim}”需要指出事实依据")
                continue
        else:
            cited = re.findall(r"\[(S\d+)\]", claim, re.I)
            records = [sources.get(basis, "")] if not cited or basis in cited else []
        quote = " ".join(check.quote.split())
        if not any(quote in " ".join(record.split()) for record in records):
            issues.append(f"“{claim}”所报依据“{basis}”内找不到逐字摘录“{check.quote}”")
        elif basis in sources and not _frequency_supported(claim, check.quote):
            issues.append(f"“{claim}”的时间或频率限定未获所摘原文“{check.quote}”支持")
        elif basis in sources and _demands_exact_alignment(claim) and not _EXACT_SOURCE.search(check.quote):
            issues.append(f"“{claim}”将位置关系强化为精确的几何条件，所引原句未给出这种精度")
    return issues


def _resolve_addressed_quote(check, by_id):
    text = check.quote.strip()
    source = check.basis.strip("[]").upper()
    addresses = list(re.finditer(r"@(S\d+)\.(\d+)\b", text))
    if not addresses or addresses[0].start() != 0:
        return check
    numbers = [int(m[2]) for m in addresses]
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        return check
    excerpt, index = by_id.get(source, ("", {}))
    originals = []
    for i, match in enumerate(addresses):
        sentence = index.get(match[0])
        end = addresses[i + 1].start() if i + 1 < len(addresses) else len(text)
        gloss = text[match.end():end].strip().lstrip(":：").strip()
        if (match[1] != source or not sentence or
                (gloss and " ".join(gloss.split()) not in " ".join(sentence.split()))):
            return check
        originals.append(sentence)
    # Preserve the original separators, including the absence of spaces in Chinese.
    contiguous = re.search(r"\s*".join(re.escape(sentence) for sentence in originals), excerpt)
    return check.model_copy(update={"quote": contiguous.group()}) if contiguous else check


def _check_report(report: BaseModel, state: AgentState) -> tuple[dict, str]:
    """Return an enforceable decision, plus an instruction if the verdict contradicts its evidence."""
    if isinstance(report, ReviewResult):
        by_id = {s["id"]: (s.get("excerpt", ""), indexed_sentences(s)) for s in state.get("evidence_sources") or []}
        checks = [_resolve_addressed_quote(check, by_id) for check in report.claim_checks]
        report = report.model_copy(update={"claim_checks": checks})
    result = report.model_dump()
    scores = result.get("dimension_scores", result)
    if isinstance(report, ReviewResult):
        score_min = minimum_body_score(state)
        thresholds = {"outline_compliance": ("大纲符合度", 80), "relevance": ("扣题度", 80),
                      "style_match": ("风格匹配", 75), "logic_flow": ("逻辑", 85)}
        if grade_research_usage(state):
            thresholds["research_usage"] = ("事实依据", 70)
    elif isinstance(report, TitleReviewResult):
        score_min = 85
        thresholds = {"relevance": ("标题相关度", 80), "type_match": ("标题类型匹配", 75),
                      "attractiveness": ("区分度与吸引力", 75)}
    else:
        score_min = 85
        thresholds = {"structure_match": ("大纲结构", 80), "completeness": ("大纲完整度", 75)}
        if not short_brief(state) and (state.get("article_style") not in {"note", "prose"} or requires_sources(state)):
            thresholds["research_reference"] = ("大纲调研参考", 70)
        if state.get("need_image"):
            thresholds["image_marks"] = ("大纲配图", 70)

    problems = list(result["review_opinions"])
    def add_problem(where: str, why: str, expected: str):
        problems.append(dict(point=len(problems) + 1, where=where, why=why, expected=expected))

    if isinstance(report, ReviewResult) and report.passed:
        claims = _claims_to_check(state)
        if claims:
            for issue in _claim_check_issues(report, state, claims):
                add_problem("逐项事实核验", issue, "核对这句的原始依据；无法支持时修改相应事实或限定词")
    numeric_checks = [(label, scores[key], minimum) for key, (label, minimum) in thresholds.items()]
    numeric_checks.append(("综合评价", result["score"], score_min))
    for label, actual, minimum in numeric_checks:
        if actual < minimum:
            add_problem(label, f"{label}评分为 {actual}，低于放行标准 {minimum}", "依据该项要求修订相关段落或候选项")
    if result.get("need_re_research"):
        add_problem("事实依据", "审稿要求补充调研", "补充所列资料并核对相关论断")
    contradiction = ""
    if result["passed"] and (problems or not result["pass_reasons"]):
        contradiction = "通过结论与必达分数、待处理意见、补查要求或通过理由不一致"
    elif not result["passed"] and (not problems or result["pass_reasons"]):
        contradiction = "退稿结论缺少具体修改依据或仍含通过理由"
    if contradiction and not problems:
        add_problem("审稿报告", contradiction, "重新审阅并提供可核对的结论和依据")
    if problems:
        result.update(passed=False, review_opinions=problems, pass_reasons=[])
    if isinstance(report, ReviewResult) and result["passed"]:
        result["policy_version"] = EDITORIAL_POLICY_VERSION
    return result, contradiction


# ============================================================
# 审稿节点工厂
# ============================================================


def _rejects_valid_h1(opinion: ReviewOpinion) -> bool:
    if not any(word in opinion.where for word in ("标题", "首行", "H1")):
        return False
    return bool(re.search(
        r"(?:去掉|去除|移除|删除|不应(?:有|使用)|不能带).{0,18}(?:井号|`?#|H1)|(?:井号|H1).{0,8}(?:多余|不合法)",
        opinion.why + " " + opinion.expected, re.I))


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
        issues = []
        source_problems = []
        if result_schema is TitleReviewResult:
            issues.extend(_planning_scope_issues(state, state.get("titles") or []))
        if result_schema is OutlineReviewResult and state.get("need_image") and not count_image_marks(state.get("outline") or ""):
            issues.append(("大纲配图", "已要求配图，但大纲没有有效配图标记", "在相应章节添加 <!-- 配图：具体画面描述 -->"))
        if result_schema is OutlineReviewResult:
            headings = _section_headings(state.get("outline") or "")
            issues.extend(unsupported_personal_history(state, state.get("outline") or ""))
            issues.extend(_planning_scope_issues(state, (title for _, title in headings)))
            for heading in unsupported_outline_measurements(state, headings):
                issues.append(("大纲标题", f"“{heading}”锁定了来源摘录中未核实的数值", "使用中性的章节标题，正文按检索依据解释"))
        if result_schema is ReviewResult:
            content = state.get("content") or ""
            issues.extend(unsupported_personal_history(state, content))
            issues.extend(unsupported_personal_effects(state, content))
            lower, upper = word_count_bounds(state.get("word_count"))
            actual = count_chars(content)
            if not lower <= actual <= upper:
                issues.append(("全文", f"正文为 {actual} 字，要求 {lower}–{upper} 字", "调整篇幅，保留章节与关键信息"))
            title = (state.get("selected_title") or "").strip()
            if title and not title_preserved(title, content):
                issues.append(("文章标题", "主标题与选定标题不一致", f"第一行使用 # {title}"))
            expected_sections = _section_headings(state.get("outline") or "")
            if expected_sections and not state.get("editor_revision") and _section_headings(content) != expected_sections:
                issues.append(("章节结构", "正文的章节、层级或顺序与已确认大纲不一致", "按已确认的大纲逐节补全并保留标题"))
            if not count_chars(content, exclude_headings=True):
                issues.append(("正文", "正文缺少章节内容", "在标题下写出实质内容"))
            expected_images = count_image_marks(state.get("outline") or "") if state.get("need_image") else 0
            if not state.get("editor_revision") and count_image_marks(content) != expected_images:
                issues.append(("配图", "正文配图标记数量与设置不一致", f"按大纲保留 {expected_images} 处配图标记"))
            issues.extend(tutorial_input_issues(state))
            source_problems = evidence_issues(state)
            issues.extend(("事实依据", reason, "核对来源，补充行内引用或删除无依据的论断") for reason in source_problems)
        if issues:
            rejection = {"passed": False, "review_opinions": [
                ReviewOpinion(point=i, where=where, why=why, expected=expected).model_dump()
                for i, (where, why, expected) in enumerate(issues, 1)
            ]}
            if source_problems and not can_recheck_existing_numbers(state, source_problems):
                rejection.update(need_re_research=True, research_type="补充调研", research_list=source_problems)
            return {"review_result": rejection}

        if not settings.enable_review and not state.get("force_review"):
            return {"review_result": {"passed": True, "skipped": True}}

        if result_schema is OutlineReviewResult and state.get("topic") and short_brief(state) and not state.get("extra_requirements"):
            preflight = bind_structured_output(ShortOutlineReview, role=model_role, enable_thinking=False)
            report = preflight.invoke([
                ("system", "你核验一篇短稿的章节计划。逐一检查题目覆盖、能否据此写稿、有无预设未经核实的结论。章节名无须预写答案。"
                 "coverage 记录如何覆盖；blocking_issues 只填写会导致文章漏答、失实或无法操作的具体问题，附相应纠正办法。"
                 "可开写时输出 blocking_issues: []，无需写保持现状的意见。"),
                ("human", task_builder(state) + editorial_brief(state))])
            passed = not report.blocking_issues
            return {"review_result": {"passed": passed, "planning_checks": report.model_dump(),
                    "pass_reasons": [report.coverage] if passed else [],
                    "review_opinions": [o.model_dump() for o in report.blocking_issues]}}

        task = task_builder(state) + editorial_brief(state) + "\n综合和全部分项一律使用百分制整数（0–100）。"
        if result_schema is ReviewResult:
            task += _claim_check_prompt(_claims_to_check(state))
        messages = [("system", review_system), ("human", task)]
        rejected = None
        for attempt in range(2):
            instruction = "上次审稿缺少有效的结构化结果，请按指定字段重新返回。"
            try:
                obj = model.invoke(messages)
                if obj is not None:
                    decision, conflict = _check_report(obj, state)
                    if isinstance(obj, ReviewResult) and not obj.passed and title_preserved(
                            state.get("selected_title") or "", state.get("content") or ""):
                        false_findings = [o.model_dump() for o in obj.review_opinions if _rejects_valid_h1(o)]
                        if false_findings and attempt == 0:
                            messages.append(("human", "首行 H1 已由程序校验。请对同一原稿重新审阅，只列出真实的内容缺陷。"))
                            continue
                        if false_findings:
                            if len(false_findings) == len(obj.review_opinions):
                                raise ValueError("审稿意见仅要求删除已经核验的合法 H1，请重试审稿服务。")
                            decision["review_opinions"] = [o for o in decision["review_opinions"] if o not in false_findings]
                    if not conflict:
                        return {"review_result": decision}
                    rejected = decision
                    details = format_review_opinions(decision)
                    instruction = f"上次报告自相矛盾：{conflict}。请重新核对稿件，返回完整的审稿报告。\n{details}"
            except (OutputParserException, ValidationError):
                pass
            if attempt == 0:
                messages.append(("human", instruction))
        if rejected is not None:
            return {"review_result": rejected}
        raise ValueError("审稿服务未返回可解析的评审结果，请重试。")

    return quality_gate_node


# ============================================================
# 打回反馈节点 + 路由
# ============================================================


def choose_ranked_title(state: AgentState, candidates=None) -> str:
    if candidates is None:
        candidates = state.get("titles") or []
    if not candidates:
        raise ValueError("没有可用于生成大纲的候选标题")
    scores = state.get("title_scores") or []
    ranks = {}
    for row in scores:
        if isinstance(row, dict):
            rank = (row.get("accuracy"), row.get("total"))
            if row.get("title") in candidates and all(type(v) in (int, float) and 0 <= v <= 10 for v in rank):
                ranks[row["title"]] = rank
    # Rank only comparable candidates; ties retain the writer's original order.
    if len(ranks) == len(candidates):
        return max(candidates, key=ranks.__getitem__)
    return candidates[0]


def review_one_title(state: AgentState) -> Dict[str, Any]:
    """A failed set may contain a publishable title. Independently review one, once."""
    titles = state.get("titles") or []
    rejected = {"review_result": state.get("review_result") or {"passed": False}}
    if (len(titles) != 3 or state.get("selected_title") or
            (not settings.enable_review and not state.get("force_review"))):
        return rejected
    eligible = [t for t in titles if isinstance(t, str) and 1 <= len(t) <= 30 and t == t.strip()
                and titles.count(t) == 1 and not any(_planning_scope_issues(state, [t]))]
    if not eligible:
        return rejected
    candidate = choose_ranked_title(state, eligible)
    prompt = (f"审核下方唯一的工作标题，原文为《{candidate}》。判断读者从这个标题能否准确了解文章的题意。"
              "score、relevance、type_match、attractiveness 四个字段全部填 0 到 100 的百分制整数。"
              "教程可陈述操作目标；笔记可写打算；开放问题不需要提前回答。仅在标题确实误导读者或超出作者授权时退回。"
              "通过时 passed=true，selected_title 原样填写工作标题，pass_reasons 写明理由，review_opinions 必须为空数组。"
              "拒绝时写具体缺陷及如何修改，不要提供其他候选。通顺且能帮助读者选读的标题符合吸引力要求。"
              + editorial_brief(state))
    model = bind_structured_output(SingleTitleReviewResult, role="reviewer", enable_thinking=False)
    messages = [("system", "你是负责独立验收候选标题的内容主编。"), ("human", prompt)]
    for attempt in range(2):
        try:
            report = model.invoke(messages)
        except (OutputParserException, ValidationError):
            return rejected
        if report is None or (report.passed and report.selected_title != candidate):
            return rejected
        decision, conflict = _check_report(report, state)
        if not conflict:
            return ({"selected_title": candidate, "review_result": decision}
                    if decision["passed"] else {"review_result": decision})
        if attempt == 0 and report.passed and report.score >= 85 and max(
                report.relevance, report.type_match, report.attractiveness) <= 10:
            messages.append(("human", "你的三个分项用了十分制，与百分制总分矛盾。请对同一个标题重新按百分制独立评分。"))
            continue
        return {"review_result": decision}


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
            "review_feedback": format_review_opinions(review) or "上一版未通过审核，请依据阶段要求检查并修订。",
            "research_suggestions": format_research_suggestions(review),
        }

    return apply_feedback_node


def review_router(state: AgentState) -> Literal["pass", "retry", "rejected"]:
    """
    质量门条件边：
    - 评审通过 -> pass（放行进入下一阶段）
    - 未通过且打回次数未达上限 -> retry（回到子图重跑）
    - 未通过且已达上限 -> rejected（停止自动推进）
    """
    review: Dict[str, Any] = state.get("review_result") or {}
    if review.get("passed"):
        return "pass"
    if state.get("review_count", 0) < state.get("max_review_rounds", 3):
        return "retry"
    return "rejected"
