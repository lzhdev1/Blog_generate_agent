import unittest

from src.blog_agent.agent.nodes.tutorial_check import tutorial_input_issues


def check(body, **state):
    return tutorial_input_issues({"article_style": "technical", "content": body, **state})


class TutorialInputsTests(unittest.TestCase):
    def test_later_example_cannot_silently_introduce_a_missing_file(self):
        body = (
            "首段演示内联数据。\n```python\nfrom io import StringIO\nsample = StringIO('007')\n```\n"
            "第二段作对比。\n```python\nimport pandas as pd\ndf = pd.read_csv('file.csv', dtype={'id': str})\n```"
        )
        self.assertEqual([item[0] for item in check(body)], ["教程输入"])
        self.assertIn("file.csv", check(body)[0][1])
        self.assertFalse(check(body, extra_requirements="使用已有的 file.csv"))

    def test_named_fixture_and_programmatic_setup_are_accepted(self):
        example = "```python\nwith open('orders.csv') as f:\n    print(f.read())\n```"
        self.assertFalse(check("将以下两行保存为 `orders.csv`。\n```csv\nid\n007\n```\n" + example))
        setup = "```python\nfrom pathlib import Path\nPath('orders.csv').write_text('id\\n007')\n```\n"
        self.assertFalse(check(setup + example))
        self.assertFalse(check("```python\nfrom io import StringIO\nimport pandas as pd\n"
                               "print(pd.read_csv(StringIO('id\\n007')))\n```"))

    def test_intentional_failure_and_non_tutorials(self):
        script = "```python\na = open('missing.txt').read()\n```"
        self.assertFalse(check("错误示例：\n" + script))
        self.assertFalse(check(script, article_style="note"))
        self.assertFalse(check("```sh\ncat missing.txt\n```"))

    def test_a_filename_in_exposition_is_not_a_fixture(self):
        read = "```python\nfrom pathlib import Path\nwith Path('items.csv').open() as f:\n    print(f.read())\n```"
        self.assertTrue(check("下一段读取 items.csv。\n" + read))
        self.assertTrue(check("先创建一份 other-items.csv。\n" + read))
        self.assertFalse(check("items.csv 内容如下。\n```csv\nid\n007\n```\n" + read))
        self.assertFalse(check("准备文件 `items.csv`，内容为 `007`。\n" + read))
        self.assertFalse(check("```sh\nprintf 'id\\n007\\n' > items.csv\n```\n" + read))

    def test_claimed_multirow_output_must_be_observable(self):
        code = "```python\nimport csv\nreader = csv.reader(['x', '007'])\nrow = next(reader)\nprint(row)\n```\n\n"
        promise = "预期输出 `['x']` 及下一行 `['007']`。"
        self.assertEqual([issue[0] for issue in check(code + promise)], ["教程输出"])
        self.assertFalse(check(code + "预期输出 `['x']`。"))
        self.assertFalse(check(code.replace("row = next(reader)\nprint(row)", "for row in reader:\n    print(row)") + promise))
