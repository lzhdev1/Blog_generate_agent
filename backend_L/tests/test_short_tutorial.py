import unittest
from unittest.mock import patch

from src.blog_agent.agent.agents import short_tutorial as tutorial


class ShortTutorialTests(unittest.TestCase):
    def setUp(self):
        self.state = dict(topic="用 Python 生成一份 SVG 文件", article_style="technical", word_count=400,
                          selected_title="一份 SVG", outline="## 生成文件\n## 验证结果")

    def test_routing_and_bounded_assembly_preserve_complete_example(self):
        self.assertTrue(tutorial.short_python_walkthrough(self.state))
        self.assertFalse(tutorial.short_python_walkthrough({**self.state, "topic": "Python 的历史"}))
        self.assertFalse(tutorial.short_python_walkthrough({**self.state, "need_image": True}))
        draft = tutorial.PythonWalkthrough(code="print(7)", stdout="7", sections=[
            tutorial.TutorialSection(explanation="甲" * 160 + "[S1]。", detail="丙" * 130),
            tutorial.TutorialSection(explanation="乙" * 160 + "[S1]。", detail="丁" * 54)])
        with patch.object(tutorial, "bind_structured_output") as model:
            model.return_value.invoke.return_value = draft
            body = tutorial.write_short_tutorial(self.state)["content"]
            model.return_value.invoke.assert_called_once()
        self.assertIn("```python\nprint(7)\n```", body)
        self.assertIn("```text\n7\n```", body)
        self.assertEqual(body.count("[S1]"), 2)
        self.assertIn("丁" * 54, body)
        self.assertNotIn("丙", body)
        self.assertIn("# 一份 SVG\n\n## 生成文件", body)

    def test_file_instructions_are_kept_even_when_an_example_uses_memory(self):
        self.state["word_count"] = 50
        draft = tutorial.PythonFileWalkthrough(code="print(7)", stdout="7", file_usage="把内存输入换成 `open(path)`。",
            sections=[tutorial.TutorialSection(explanation="实例", detail="补" * 40) for _ in range(2)])
        with patch.object(tutorial, "bind_structured_output") as model:
            model.return_value.invoke.return_value = draft
            body = tutorial.write_short_tutorial(self.state)["content"]
        self.assertIs(model.call_args.args[0], tutorial.PythonFileWalkthrough)
        self.assertIn(draft.file_usage, body)
