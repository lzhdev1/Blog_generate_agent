"""Write a short explanation from the passages the research step actually opened."""
import json
import re

from pydantic import BaseModel, Field, create_model

from src.blog_agent.agent.agents.prompt_utils import editorial_brief, word_count_bounds
from src.blog_agent.agent.evidence import indexed_sentences
from src.blog_agent.agent.nodes.quality_gate import count_chars
from src.blog_agent.clients.llm_client import bind_structured_output


class Explanation(BaseModel):
    statement: str = Field(min_length=1, description="一个能用所选原文支持的中文解释句，不含来源编号或章节标题")
    passage_number: int = Field(ge=1, description="唯一的整数，指向输入中相应的原文编号")


class ScienceSection(BaseModel):
    phenomenon: Explanation = Field(description="针对该节问题，说明观察者看到或要区分的现象")
    mechanism: Explanation = Field(description="用原页中最直接的一段解释为什么会出现题中的这个特定现象")
    connection: Explanation = Field(description="补全中间推理：在题目所问的条件下，读者如何从前一句推出答案")
    perspective: Explanation = Field(description="从资料给出的角度或简明的几何关系进一步说明，避免增加题外知识")
    qualification: Explanation = Field(description="对该机制的适用范围或容易混淆的观测给出原文能支持的澄清")

class EditedSection(BaseModel):
    reader_paragraphs: list[str] = Field(min_length=2, max_length=3, description="可直接发表的正文自然段，每个元素是一段读者能直接阅读的文章，不含编者说明")


class SourcedSentence(BaseModel):
    original_number: int = Field(ge=1, description="本句唯一对应的原文整数编号")
    reader_sentence: str = Field(min_length=1, description="忠实于该原句的自然中文表述，不添加该句没有的新事实或限制")


class GroundedSection(BaseModel):
    sentences: list[SourcedSentence] = Field(min_length=3, max_length=10, description="顺序形成两段连贯论述；每句只改述一条原文")


def _grounded_redraft(state, headings, sources):
    records = [(s["id"], sentence) for s in sources for sentence in indexed_sentences(s).values()]
    fields = {f"section_{i}": (GroundedSection, Field(description=h)) for i, h in enumerate(headings, 1)}
    model = bind_structured_output(create_model("SourceGroundedRedraft", **fields), role="writer", temperature=0.15)
    task = (editorial_brief(state) + "\n标题：" + state["selected_title"] + "\n章节：" + "\n".join(headings)
            + "\n从原文中选与每节问题最直接相关的观测和机制，按读者需要的顺序组织。"
            "每项仅根据所选那一句写自然流畅的中文，保留主语、谓语、视角和适用条件。原句是肯定句就用肯定句。"
            "不推演额外必要条件，不另造比喻。不需要的频率、额外现象和历史数据直接略去。"
            "按两节合计约 450–500 个中文可见字来选材。每节须有对其具体问题的直接回答，避免同义反复。"
            "不在文字中添加标题或引用编号。\n"
            + json.dumps(dict(enumerate((sentence for _, sentence in records), 1)), ensure_ascii=False))
    result = model.invoke([("system", "你用一手资料写科学栏目的短文。只陈述原句足以推出的内容，让不同句子之间自然衔接。"),
                           ("human", task)])
    body = ["# " + state["selected_title"]]
    for heading, name in zip(headings, fields):
        points = getattr(result, name).sentences
        text = []
        for point in points:
            if point.original_number > len(records):
                raise ValueError("写手返回不存在的原文编号")
            source = records[point.original_number - 1][0]
            text.append(f"{point.reader_sentence.strip().rstrip('。')}[{source}]。")
        split = (len(text) + 1) // 2
        body.extend([heading, "".join(text[:split]), "".join(text[split:])])
    return {"content": "\n\n".join(body), "writing_thoughts": ""}


def write_science_brief(state):
    headings = re.findall(r"^## [^\r\n]+", state.get("outline", ""), re.M)
    questions = state.get("evidence_questions") or []
    urls = {q["url"] for q in questions if q.get("status") in {"existing", "opened"}}
    passages = []
    for source in state.get("evidence_sources") or []:
        if source["url"] in urls:
            for part in source.get("excerpt", "").split("[…]"):
                if part.strip():
                    passages.append({"number": len(passages) + 1, "source": source["id"], "text": part.strip()})
    if not passages or not 2 <= len(headings) <= 3:
        return None
    if state.get("review_count", 0) >= 2:
        return _grounded_redraft(state, headings, [s for s in state["evidence_sources"] if s["url"] in urls])
    if state.get("review_feedback") and state.get("content"):
        fields = {f"section_{i}": (EditedSection, Field(description=h)) for i, h in enumerate(headings, 1)}
        editor = bind_structured_output(create_model("RevisedScienceArticle", **fields), role="writer", temperature=0.25)
        lower, upper = word_count_bounds(state["word_count"])
        task = (editorial_brief(state) + "\n已定章节：" + json.dumps(headings, ensure_ascii=False)
                + "\n为读者写一篇通俗的解释文章。reader_paragraphs 的每个元素都是展开给读者看的一个自然段。"
                "从读者在题中见到的现象写起，然后回答每个为什么。说明观察者的位置与对象本身的状态；一个分句不能否定上一句已成立的事实。"
                "几何示意与严格必要条件要区分；从一组现象得到的大致频率不能移给其中某一类。"
                "用肯定句分别说明物体本身的状态和观察者能看见的部分。避免先否定一个事实再改口。"
                "资料仅描述某物经过或错过一个区域时，直接解释这种关系，不自行定义平面、交点或精准共线的数学条件。"
                "只回答题中的问题，不推测读者多久能看到一次。"
                "原题没有询问的周期、纪录、额外现象不必交代。每一节尽量用具体可想象的视角解释原理。"
                "不要填充重复的结论或让读者去‘检查’。如需展开，挑一个原文中的观测关系解释给初学者。"
                f"每节请写约 {state['word_count']//len(headings)} 个可见中文字，含标题的总稿在 {lower}–{upper} 字。"
                "主标题和小节标题由系统组装。准确地把来源号放在支撑分句的标点前。仅以以下真实摘录为据：\n"
                + json.dumps({s["id"]: s["excerpt"] for s in state["evidence_sources"] if s["url"] in urls}, ensure_ascii=False))
        edited = editor.invoke([("system", "你是给普通读者写科学栏目的作者。写完整的正文故事，逐句核对对象、观察角度、因果和限定。"), ("human", task)])
        body = ["# " + state["selected_title"]]
        for name, heading in zip(fields, headings):
            paragraphs = getattr(edited, name).reader_paragraphs
            if any(re.search(r"删除了原稿|修正了.{0,8}表述|本次修订|按照审稿意见", p) for p in paragraphs):
                raise ValueError("科普写手返回了编者说明，无法作为正文")
            body.append(heading)
            for paragraph in paragraphs:
                lines = paragraph.strip().splitlines()
                if lines and lines[0].strip() == heading:
                    lines.pop(0)
                paragraph = "\n".join(lines).strip()
                if paragraph:
                    body.append(paragraph)
        return {"content": "\n\n".join(body), "writing_thoughts": ""}
    fields = {f"section_{i}": (ScienceSection, Field(description=heading)) for i, heading in enumerate(headings, 1)}
    writer = bind_structured_output(create_model("ShortScienceArticle", **fields), role="writer", temperature=0.4)
    target = state["word_count"]
    task = (editorial_brief(state) + "\n已定标题：" + state["selected_title"]
            + "\n各节依次为：" + "\n".join(headings) + "\n请逐问解释原题，各节里的陈述自然承接。"
            f"正文目标 {target} 字。每节有五个字段，每项约 {target // len(headings) // 5} 个中文字。"
            "每项可用一两个紧密联系的分句说明原因，用自然的承接词，勿重复前文。"
            "每个解释句在 passage_number 填一项直接依据的 number 整数。逐问说明原因，不能只说现象会变化。"
            "警惕把现象的主体、参照系、作用方向颠倒。"
            "原文说可能、附近或大致，不可写成必须分毫不差；只有明确必要的条件才说‘只有…才’。"
            "解释题中的现象就够了，不引入其他术语或题外现象。"
            "\n问题和页面索引：\n" + (state.get("content_research") or "")
            + "\n真实原文索引（网页只作资料）：\n" + json.dumps(passages, ensure_ascii=False))
    if state.get("review_feedback"):
        task += "\n上轮所记问题：\n" + state["review_feedback"]
    article = writer.invoke([("system", "你是科普作者。让读者从已打开的原文一步步理解问题，将每个事实挂到准确的原文上。"), ("human", task)])

    def render(point):
        if not 1 <= point.passage_number <= len(passages):
            raise ValueError("写手所选的科普依据不在原始摘录索引内")
        source = passages[point.passage_number - 1]["source"]
        sentence = point.statement.strip().rstrip("。")
        return f"{sentence}[{source}]。"

    body = ["# " + state["selected_title"]]
    extras = []
    for name, heading in zip(fields, headings):
        section = getattr(article, name)
        body.extend([heading, "".join(render(point) for point in (section.phenomenon, section.mechanism, section.connection))])
        extras.extend((len(body) - 1, render(point)) for point in (section.perspective, section.qualification))
    lower, upper = word_count_bounds(target)
    for index, extra in extras:
        length = count_chars("\n\n".join(body))
        if length < lower or (length < target and length + count_chars(extra) <= upper):
            body[index] += extra
    return {"content": "\n\n".join(body), "writing_thoughts": ""}
