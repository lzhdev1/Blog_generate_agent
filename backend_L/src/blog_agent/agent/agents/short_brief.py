"""Planning for short manuscripts whose deliverable is already specified by the author."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from src.blog_agent.agent.agents.prompt_utils import style_desc


class ShortOutline(BaseModel):
    headings: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50, pattern=r"^[^#\r\n]+$")]] = Field(
        min_length=2, max_length=3, description="二至三个独立的章节名称，不含 Markdown 标记或章节说明")

    def markdown(self):
        return "\n".join(f"## {heading}" for heading in self.headings)


def short_brief(state):
    target = state.get("word_count")
    return bool(target and target <= 600 and not state.get("need_image")
                and state.get("article_style") in {"technical", "popular_science", "note", "prose"})


def title_request(state):
    return (f"为作者选题《{state.get('topic', '')}》拟三个简洁的不同中文标题。"
            f"体裁为{style_desc(state)}。优先准确说明本文要回答的问题或完成的操作。"
            "有几个并列要求时兼顾它们；不要新增竞品、心理疗效、统计、测量值或题外承诺。"
            "个人笔记的标题可以写一种打算。每项尽量控制在十八字左右，最多三十个字符。")


def outline_request(state):
    return (f"为《{state.get('selected_title', '')}》写短稿大纲。原始选题是《{state.get('topic', '')}》。"
            f"体裁为{style_desc(state)}。从选题中找出读者需要得到回答的每个问题，合理分配到章节中。"
            "通常只要两至三个同级的 ## 章节名；每个标题各占一行，不写段落示范、个人经历、结论或编者按。"
            "章节名要便于读者知道这一节会回答什么。教程留出实操与结果验证的位置；"
            "两种现象的成因须分别交代。明确的作者结构要求优先。")
