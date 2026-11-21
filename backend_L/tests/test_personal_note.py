import unittest
from unittest.mock import patch

from src.blog_agent.agent.agents import personal_note


class PersonalNoteTests(unittest.TestCase):
    def setUp(self):
        self.state = {"topic": "个人笔记：睡前写下一件明天想做的小事", "article_style": "note"}

    def test_old_manuscript_claims_fail_even_with_a_style_brief(self):
        sentences = (
            "我曾尝试列出五项，结果因压力过大而失眠。",
            "我通常选择手机备忘录或纸质便签。",
            "我发现，当那行字足够具体且可执行时，次日清晨的启动阻力最小。",
            "过去列长清单常让我醒来就感到压力，仿佛未完成项在催促。",
        )
        for sentence in sentences:
            for extra in ("", "请用简短句子。", "不允许虚构故事。"):
                with self.subTest(sentence=sentence, extra=extra):
                    issues = personal_note.unsupported_personal_history(
                        {**self.state, "extra_requirements": extra}, sentence)
                    self.assertTrue(issues)

    def test_prospective_and_author_supplied_material(self):
        for sentence in ("我打算拿出一张纸。", "如果我曾尝试列出五项，结果会怎样？",
                         "比如，我通常选择纸笔，那我会给这张纸找个位置。"):
            with self.subTest(sentence=sentence):
                self.assertFalse(personal_note.unsupported_personal_history(self.state, sentence))
        for extra in ("作者素材：曾尝试列出五项。", "请虚构一篇手记。", "尝试列出五项"):
            with self.subTest(extra=extra):
                self.assertFalse(personal_note.unsupported_personal_history(
                    {**self.state, "content_extra_requirements": extra}, "我曾尝试列出五项。"))

    def test_writer_receives_only_author_material_and_approved_headings(self):
        state = {**self.state, "word_count": 500, "selected_title": "今晚的一件事",
                 "outline": "## 今晚写什么\n我曾坚持三年，感觉精力充沛。\n## 明早怎么选",
                 "writing_thoughts": "我曾参加七场马拉松。"}
        with patch.object(personal_note, "bind_structured_output") as bind:
            writer = bind.return_value
            writer.invoke.side_effect = lambda _: bind.call_args.args[0](
                section_1="## 今晚写什么\n我打算留一点空白。", section_2="明早再选也可以。")
            result = personal_note.write_personal_note(state)
        writer_input = str(writer.invoke.call_args.args)
        self.assertNotIn("坚持三年", writer_input)
        self.assertNotIn("马拉松", writer_input)
        self.assertEqual(result["content"], "# 今晚的一件事\n\n## 今晚写什么\n\n我打算留一点空白。"
                         "\n\n## 明早怎么选\n\n明早再选也可以。")

    def test_rejected_note_cannot_borrow_unverified_neuroscience(self):
        for sentence in ("多任务预设容易让大脑提前进入执行模式。",
                         "一个可触摸的动作更可能被记住。"):
            self.assertTrue(personal_note.unsupported_personal_effects(self.state, sentence))
        for sentence in ("这样是否更容易被记住？我还说不好。", "这不一定更容易被记住。",
                         "我想把卡片留在书桌上。", "这种提示更容易被记住[S1]。"):
            self.assertFalse(personal_note.unsupported_personal_effects(self.state, sentence))
