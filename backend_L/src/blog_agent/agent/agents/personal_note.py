"""Write personal reflections from the author's brief, independently of research prose."""
import re
from typing import Annotated

from pydantic import Field, StringConstraints, create_model

from src.blog_agent.agent.agents.prompt_utils import IMAGE_MARKER_RE, editorial_brief, word_count_bounds
from src.blog_agent.agent.evidence import personal_reflection
from src.blog_agent.clients.llm_client import bind_structured_output


_HEADING = re.compile(r"^ {0,3}#{2,3}\s+\S")
_PAST_SELF = re.compile(
    r"我(?:曾(?:经)?(?:在|把|尝试|试|用|写|做|看|遇|听|记|参加|为了|连续|因为|以为|花|将)|"
    r"亲(?:眼|身|耳)|尝试过|犹豫过|坚持了|试过|记得(?:那|有一次)|第一次.{0,12}时)|"
    r"(?:后来|那天|那晚|当时|昨晚|昨天)我(?:才|发现|试|写|遇|听|看|把|做|去)|"
    r"(?:刚开始|一开始).{0,10}时[，,]?我常|"
    r"我(?:通常会?|习惯于?|每(?:天|晚)都?|总是)(?:选择|使用|拿出|写下|打开|挑选|记录|列出)|"
    r"我发现.{0,48}(?:次日|第二天|隔天).{0,16}(?:最小|少了|更容易|减轻|改善)|"
    r"(?:过去|以往|从前|以前).{0,22}(?:(?:常|总|经常)?(?:令我|让我|使我)|我(?:常|总|习惯))"
)
_AUTHOR_CONTEXT = re.compile(
    r"虚构(?:故事|叙事|手记|笔记|情节|人物)|(?:允许|可以|请|采用|以|按|授权|写)(?:合理)?虚构|编一个故事|想象故事|"
    r"亲历[：:]|作者素材[：:]|我的回忆|我的往事|曾经|昨天|昨晚|去年|上周|小时候|"
    r"我.{0,15}(?:过|了|以前|过去|那天|那晚|当时|从前)|(?:那天|那晚|当时|从前)我"
)
_HYPOTHETICAL = re.compile(r"假如|假若|假设|如果|要是|倘若|设想|想象|比方(?:说)?|举(?:个|一)?例|例如|比如")
_ASSERTED_EFFECT = re.compile(
    r"(?:让|令|使|促使|帮助)(?:人的|我们(?:的)?|我的)?(?:大脑|神经系统).{0,12}"
    r"(?:进入|切换|释放|卸载|停止|知道|恢复|关机)|"
    r"(?:更可能|更容易|更易)(?:被(?:人)?记住|入睡|缓解焦虑)|"
    r"(?:(?:这|它)是(?:一[种次])?认知卸载|能(?:强行)?切断.{0,10}反刍)"
)
_OPEN_QUESTION = re.compile(r"能否|是否|会不会|未必|不一定|并不能|不能说明|不敢说")


def _author_context(state):
    brief = "\n".join(state.get(k) or "" for k in
                      ("topic", "purpose", "extra_requirements", "content_extra_requirements"))
    context = re.sub(r"(?:不允许|禁止|不得|不能|不可|不要|切勿|请勿)(?:合理)?虚构", "", brief)
    return brief, bool(_AUTHOR_CONTEXT.search(context) or _PAST_SELF.search(context))


def unsupported_personal_history(state, text):
    """Catch explicit memories in a topic-only reflection; leave supplied material to semantic review."""
    if not personal_reflection(state):
        return []
    brief, has_context = _author_context(state)
    if has_context:
        return []
    issues = []
    for sentence in re.split(r"(?<=[。！？!?])|\n+", text):
        match = _PAST_SELF.search(sentence)
        if not match or _HYPOTHETICAL.search(sentence[:match.start()]) or sentence.rstrip().endswith(("？", "?")):
            continue
        # Action fragments can be user-provided without an explicit first-person subject.
        action = re.split(r"[，,。；;：:！？!?]", re.sub(
            r"^我(?:曾经?|通常会?|习惯于?|每(?:天|晚)都?|总是)?", "", sentence[match.start():]), maxsplit=1)[0].strip()
        if len(action) >= 4 and action in brief:
            continue
        issues.append(("作者素材", f"“{sentence.strip()[:100]}”陈述了作者未提供的亲历",
                       "删去这段回忆；可就同一选择写当下的取舍或清楚标出的假设。无需补查外部资料。"))
    return issues[:3]


def unsupported_personal_effects(state, text):
    """Sources or genuine questions are needed for external causal claims in a personal reflection."""
    if not personal_reflection(state):
        return []
    issues = []
    for sentence in re.split(r"(?<=[。！？!?])|\n+", text):
        if (_ASSERTED_EFFECT.search(sentence) and not _OPEN_QUESTION.search(sentence)
                and not re.search(r"\[S\d+\]", sentence)):
            issues.append(("外部因果依据", f"“{sentence.strip()[:130]}”将个人取舍写成了没有出处的普遍作用或机制",
                           "写出选择的具体理由。若保留客观功效，须给出支持该作用的原始资料。"))
    return issues[:3]


def write_personal_note(state):
    """Only author-supplied fields and approved heading labels are admissible as writing inputs."""
    sections = []
    leading_images = []
    for line in (state.get("outline") or "").splitlines():
        if _HEADING.match(line):
            sections.append((line.strip(), []))
        else:
            markers = sections[-1][1] if sections else leading_images
            markers.extend(m.group() for m in IMAGE_MARKER_RE.finditer(line))
    if not sections:
        sections.append(("", []))

    title = state.get("selected_title") or state.get("topic", "")
    target = state.get("word_count") or 800
    lower, upper = word_count_bounds(target)
    heading_chars = sum(len(re.sub(r"[#\s]", "", h)) for h, _ in sections) + len(title)
    target_per_section = max(1, (target - heading_chars) // len(sections))
    body_string = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    fields = {f"section_{n}": (body_string, Field(description="这一节的正文，可包含多个自然段。"))
              for n in range(1, len(sections) + 1)}
    schema = create_model("PersonalNoteSections", **fields)
    writer = bind_structured_output(schema, role="writer", temperature=0.5)
    headings = "\n".join(f"section_{i} 对应 {h or '全文'}" for i, (h, _) in enumerate(sections, 1))
    task = (f"为《{title}》撰写个人手记。每个字段从自然段开始，程序会原样组装已确认的标题、配图。"
            f"每节约 {target_per_section} 个可见字，全文含标题须在 {lower}–{upper} 字之间。\n{headings}"
            + editorial_brief(state))
    _, has_context = _author_context(state)
    if not has_context:
        task += ("\n本稿的素材只有作者的题意，没有口述往事。请直接从眼下的一个选择或疑问落笔，"
                 "用选项之间具体的差别解释这个选择。每一节的叙述都发生在行动之前，"
                 "将可能改变主意的条件也写成假设。动机同样只能是眼下的考量；不得用以往的习惯、"
                 "前一次失败、曾经的感受或已经出现的效果解释动机。实物和场景可作为明确的举例。"
                 "写清自己愿意花什么工夫、愿意舍掉哪个选项，原因落在这个选择本身。"
                 "真的拿不准，就保留疑问。不要借用神经科学、记忆、睡眠或身心疗效来为个人决定找论据。"
                 "写成可以留给自己读的自然笔记，少用抽象的概念、评估术语和格言。")
    if state.get("review_feedback"):
        task += "\n上轮具体问题如下。围绕作者简报重新表达，退稿意见里的描述不是作者提供的素材。\n" + state["review_feedback"]
    system = ("写一篇有具体取舍的第一人称手记。以作者提供的经历为限，给了虚构授权才按设定写故事。"
              "只给选题时采用当下或将来的视角：提出自己想试的做法、犹豫之处和选择理由。"
              "具体例子可以展开，但需让读者读得出它是设想。不要生成过去的实践、形成的习惯、"
              "已观察的结果，或给选择附会上未经证实的心理、生理效果。"
              "各节要写不同内容，可以让读者看到一个具体决定如何做出；避免反复声明素材有限，避免研究报告或对读者训话的口吻。"
              "所有章节标题已确定，字段中只写正文。")
    result = writer.invoke([("system", system), ("human", task)])
    if result is None:
        raise ValueError("写手没有返回手记段落")
    parts = [f"# {title}", *leading_images]
    for i, (heading, markers) in enumerate(sections, 1):
        body = getattr(result, f"section_{i}")
        first_line, separator, remainder = body.partition("\n")
        if heading and separator and first_line.strip() == heading:
            body = remainder.strip()
        parts.extend([heading, *markers, body])
    return {"content": "\n\n".join(p for p in parts if p), "writing_thoughts": state.get("writing_thoughts") or ""}
