"""Run the production editorial gates against deterministic, offline reviewer responses."""
import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("LLM_API_KEY", "offline")
os.environ.setdefault("LLM_BASE_URL", "http://localhost")

from pydantic import ValidationError

from src.blog_agent.agent.agents.prompt_utils import editorial_brief
from src.blog_agent.agent.agents.title_prompts import TitleList
from src.blog_agent.agent.graphs import outline_graph, title_graph
from src.blog_agent.agent.nodes import quality_gate as gates
from src.blog_agent.clients.image_client import ImageClient
from src.blog_agent.service import agent_service


class EditorialQualityTests(unittest.TestCase):
    def test_diagram_alignment_cannot_be_read_as_a_zero_tolerance_requirement(self):
        original = "The objects are in a straight line in this diagram."
        claim = "若三者未严格共线，阴影就无法形成遮挡[S1]。"
        state = {"article_style": "popular_science", "evidence_sources": [{"id": "S1", "excerpt": original}]}
        report = Mock(claim_checks=[gates.ClaimCheck(item=1, basis="S1", quote=original)])
        self.assertIn("精确", gates._claim_check_issues(report, state, [claim])[0])
        self.assertFalse(gates._demands_exact_alignment("出现这种现象无需严格共线。"))
        self.assertFalse(gates._demands_exact_alignment("即使未严格共线，仍可发生部分重叠。"))
        self.assertTrue(gates._EXACT_SOURCE.search("The axes must be precisely aligned."))

    def setUp(self):
        self.body = "# 读书会\n\n## 开场\n" + "窗外下着细雨，我翻开了书。" * 15
        self.state = dict(content=self.body, selected_title="读书会", article_style="prose",
                          word_count=200, outline="## 开场", purpose="与同伴讨论")
        self.dims = dict(outline_compliance=92, relevance=93, style_match=90, logic_flow=91, research_usage=0)
        self.common = dict(passed=True, score=88, pass_reasons=["各节紧扣主题"])
        self.enterContext(patch.object(gates.settings, "enable_review", True))

    def gate(self, schema, reply, state=None):
        with patch.object(gates, "bind_structured_output") as model:
            model.return_value.invoke.return_value = reply
            node = gates.make_quality_gate_node("主编", lambda s: "审稿", schema)
            result = node(self.state if state is None else state)["review_result"]
            return result, model.return_value.invoke

    def test_contradictory_body_report_never_grants_clearance(self):
        opinions = [dict(point=1, where="开场", why="论证缺失", expected="补充理由")]
        reply = gates.ReviewResult(**{**self.common, "score": 42}, review_opinions=opinions,
                                   dimension_scores={**self.dims, "logic_flow": 40})
        result, invoke = self.gate(gates.ReviewResult, reply)
        self.assertFalse(result["passed"])
        self.assertNotIn("policy_version", result)
        self.assertEqual(invoke.call_count, 2)
        self.assertIn("与同伴讨论", invoke.call_args.args[0][1][1])
        self.assertIn("论证缺失", str(result["review_opinions"]))
        self.assertIn("逻辑评分为 40", str(result["review_opinions"]))
        self.assertFalse(result["pass_reasons"])

    def test_short_complete_prose_has_its_own_standard(self):
        reply = gates.ReviewResult(**self.common, dimension_scores=self.dims)
        result, invoke = self.gate(gates.ReviewResult, reply)
        self.assertTrue(result["passed"])
        self.assertEqual(result["policy_version"], 1)
        invoke.assert_called_once()
        for state in [{**self.state, "outline": "## 开场\n## 讨论"}, {**self.state, "word_count": 800}]:
            self.assertEqual(gates.minimum_body_score(state), 90)

    def test_editor_rechecks_legal_h1_on_the_same_manuscript(self):
        bogus = dict(point=1, where="首行标题", why="H1 前的井号多余", expected="去掉井号")
        actual = dict(point=2, where="结尾", why="提出讨论却未交代主题", expected="写出讨论的问题")
        passed = gates.ReviewResult(**self.common, dimension_scores=self.dims)
        false_reject = gates.ReviewResult(passed=False, score=87, dimension_scores=self.dims,
                                          review_opinions=[bogus])
        mixed = gates.ReviewResult(passed=False, score=87, dimension_scores=self.dims,
                                   review_opinions=[bogus, actual])
        for second, expected_pass in [(passed, True), (mixed, False)]:
            with self.subTest(second=second), patch.object(gates, "bind_structured_output") as bind:
                invoke = bind.return_value.invoke
                invoke.side_effect = [false_reject, second]
                node = gates.make_quality_gate_node("主编", lambda s: s["content"])
                decision = node(self.state)["review_result"]
                self.assertEqual(decision["passed"], expected_pass)
                self.assertEqual(invoke.call_count, 2)
                self.assertIn(self.body, invoke.call_args.args[0][1][1])
                self.assertEqual(decision["review_opinions"], [] if expected_pass else [actual])
        with patch.object(gates, "bind_structured_output") as bind:
            bind.return_value.invoke.return_value = false_reject
            node = gates.make_quality_gate_node("主编", lambda s: s["content"])
            with self.assertRaisesRegex(ValueError, "合法 H1"):
                node(self.state)
            self.assertEqual(bind.return_value.invoke.call_count, 2)

    def test_personal_brief_keeps_author_input_distinct_from_generated_material(self):
        state = {**self.state, "topic": "桌边留一本书", "article_style": "note",
                 "extra_requirements": "书是向同事借的",
                 "content_extra_requirements": "允许虚构一个结尾",
                 "content_research": "检索到另一位读者在书上贴了蓝签"}
        brief = editorial_brief(state)
        self.assertIn("桌边留一本书", brief)
        self.assertIn("书是向同事借的", brief)
        self.assertIn("允许虚构一个结尾", brief)
        self.assertNotIn("蓝签", brief)
        self.assertNotIn(self.body, brief)
        reply = gates.ReviewResult(**self.common, dimension_scores=self.dims)
        _, invoke = self.gate(gates.ReviewResult, reply, state)
        self.assertIn(brief, invoke.call_args.args[0][1][1])
        self.assertIn("只有选题时", editorial_brief({"topic": "整理书桌"}))

    def test_positive_review_requires_all_claims_and_verbatim_provenance(self):
        source = {"id": "S1", "title": "公园观测记录", "excerpt": "公园通常在春季开放。",
                  "url": "https://example.org/park"}
        body = "# 公园\n\n## 开场\n公园通常在春季开放[S1]。这个公园每年都按时开放[S1]。"
        state = {**self.state, "topic": "公园的开放季", "word_count": 100, "selected_title": "公园",
                 "article_style": "popular_science", "content": body, "evidence_sources": [source]}
        dims = {**self.dims, "research_usage": 90}
        checked = dict(item=1, basis="S1", quote="通常在春季开放")
        for second in (None, checked, dict(item=2, basis="S99", quote="每年都按时"),
                       dict(item=2, basis="S1", quote="每年都按时"),
                       dict(item=2, basis="表达", quote="每年都按时"),
                       dict(item=2, basis="无据", quote="每年都按时")):
            with self.subTest(second=second):
                reply = gates.ReviewResult(**self.common, dimension_scores=dims,
                                           claim_checks=[checked] + ([second] if second else []))
                result, invoke = self.gate(gates.ReviewResult, reply, state)
                self.assertFalse(result["passed"])
                self.assertTrue(any(p["where"] == "逐项事实核验" for p in result["review_opinions"]))
                prompt = invoke.call_args.args[0][1][1]
                self.assertIn("1. 公园通常在春季开放", prompt)
                self.assertIn("2. 这个公园每年都按时开放", prompt)

        state["content"] = body.split("。")[0] + "。"
        valid = gates.ReviewResult(**self.common, dimension_scores=dims, claim_checks=[checked])
        result, invoke = self.gate(gates.ReviewResult, valid, state)
        self.assertTrue(result["passed"])
        invoke.assert_called_once()

    def test_personal_claims_only_match_author_fields(self):
        body = "# 我想读书\n\n昨晚我读了一本书。愿望像一颗种子。"
        state = dict(topic="读书笔记", article_style="note", content=body, outline="昨晚我读了一本书",
                     content_research="昨晚我读了一本书", extra_requirements="作者在读一本书")
        claims = gates._claims_to_check(state)
        def issues(basis):
            report = gates.ReviewResult(**self.common, dimension_scores=self.dims, claim_checks=[
                dict(item=1, basis="作者", quote=basis), dict(item=2, basis="表达", quote="像一颗种子")])
            return gates._claim_check_issues(report, state, claims)
        self.assertTrue(issues("昨晚我读了一本书"))
        state["extra_requirements"] = "昨晚我读了一本书。"
        self.assertFalse(issues("昨晚我读了一本书"))

    def test_adjacent_review_addresses_verify_each_quote_and_its_source(self):
        sources = [
            dict(id="S1", title="Lamp illumination", url="https://example.org/lights",
                 excerpt="A lamp illuminates the near side. The far side remains dark."),
            dict(id="S2", title="第二间灯室", url="https://example.org/other",
                 excerpt="The walls reflect light. The floor is green."),
        ]
        state = {**self.state, "topic": "灯的照明方向", "article_style": "popular_science", "evidence_sources": sources,
                 "word_count": 100, "content": "# 读书会\n\n## 开场\n由于近侧朝向灯，近侧明亮而远侧保持昏暗[S1]。"}
        for quote, expected in [
            ("@S1.1: A lamp illuminates the near side. @S1.2 The far side remains dark.", True),
            ("@S1.1: A lamp illuminates the far side. @S1.2 The far side remains dark.", False),
            ("@S1.1: A lamp illuminates the near side. @S2.2 The floor is green.", False),
            ("@S1.1: A lamp illuminates the near side. @S1.1 A lamp illuminates the near side.", False),
        ]:
            report = gates.ReviewResult(**self.common, dimension_scores={**self.dims, "research_usage": 95},
                                        claim_checks=[dict(item=1, basis="S1", quote=quote)])
            with self.subTest(quote=quote):
                result, invoke = self.gate(gates.ReviewResult, report, state)
                self.assertEqual(result["passed"], expected, result.get("review_opinions"))
                if expected:
                    self.assertEqual(result["claim_checks"][0]["quote"], sources[0]["excerpt"])
                    invoke.assert_called_once()
                else:
                    self.assertIn("逐项事实核验", str(result["review_opinions"]))
        chinese_quote = "@S1.1: 灯照亮近侧。 @S1.2 远侧保持昏暗。"
        report = gates.ReviewResult(**self.common, dimension_scores={**self.dims, "research_usage": 95},
                                    claim_checks=[dict(item=1, basis="S1", quote=chinese_quote)])
        for separator, contiguous in [("", True), ("\n", True), (" […] ", False)]:
            excerpt = "灯照亮近侧。" + separator + "远侧保持昏暗。"
            localized = {**state, "evidence_sources": [{**sources[0], "excerpt": excerpt}]}
            with self.subTest(separator=separator):
                result, _ = self.gate(gates.ReviewResult, report, localized)
                self.assertEqual(result["passed"], contiguous, result.get("review_opinions"))
                if contiguous:
                    self.assertEqual(result["claim_checks"][0]["quote"], excerpt)

    def test_frequency_check_keeps_the_predicate_and_polarity(self):
        self.assertFalse(gates._frequency_supported("每月都能观测到它", "an event rather than a sight every month"))
        self.assertFalse(gates._frequency_supported("大多数时候，轨道有倾角", "the orbit is tilted"))
        self.assertTrue(gates._frequency_supported("每月都开放", "it opens every month"))
        self.assertTrue(gates._frequency_supported("并非每月都举办", "occasionally, not every month"))
        state = {"topic": "读书", "article_style": "note",
                 "content": "我没有计时，也没有足够证据断定效率提高了30%。我希望早一点开始。"}
        self.assertNotIn("30%", "".join(gates._claims_to_check(state)))

    def test_omitted_section_or_heading_only_draft_cannot_be_approved(self):
        for state in [{**self.state, "outline": "## 开场\n## 讨论"},
                      dict(content="# 标题\n## 开场", outline="## 开场", word_count=100)]:
            decision, invoke = self.gate(gates.ReviewResult, None, state)
            self.assertFalse(decision["passed"])
            invoke.assert_not_called()

    def test_research_and_unresolved_opinions_override_positive_verdict(self):
        reply = gates.ReviewResult(**self.common, dimension_scores=self.dims, need_re_research=True,
                                   research_type="补充调研", research_list=["核对统计方法"])
        result, _ = self.gate(gates.ReviewResult, reply)
        self.assertFalse(result["passed"])
        self.assertTrue(result["need_re_research"])
        state = {**self.state, "article_style": "technical"}
        result, invoke = self.gate(gates.ReviewResult, reply, state)
        self.assertFalse(result["passed"])
        self.assertTrue(result["need_re_research"])
        invoke.assert_not_called()

    def test_editor_revision_forces_review_of_typeset_manuscript(self):
        reply = gates.ReviewResult(**self.common, dimension_scores=self.dims)
        state = {**self.state, "force_review": True, "editor_revision": True, "need_image": True,
                 "outline": "## 开场\n<!-- 配图：室内读书的桌面 -->"}
        with patch.object(gates.settings, "enable_review", False):
            result, invoke = self.gate(gates.ReviewResult, reply, state)
        invoke.assert_called_once()
        self.assertEqual(result["policy_version"], 1)
        bad, invoke = self.gate(gates.ReviewResult, reply, {**state, "selected_title": "另一个标题"})
        self.assertFalse(bad["passed"])
        invoke.assert_not_called()

    def test_layout_images_and_source_ids_never_change_the_manuscript_length(self):
        label = "# 读书会\n\n## 开场\n**书单**见[书目](https://example.org/book_(guide))。"
        draft = label + "\n<!-- 配图：照片 -->"
        typeset = label + "[S12]\n![配图1](/images/task_123_456.jpg)\n\n[S12]: <https://example.org/very/long/reference>"
        expected = len("读书会开场书单见书目。")
        self.assertEqual(gates.count_chars(draft), expected)
        self.assertEqual(gates.count_chars(typeset), expected)
        self.assertEqual(gates.count_chars("```md\n[S1]\n```"), 4)

    def test_title_and_outline_subscores_are_enforced(self):
        title = gates.TitleReviewResult(**self.common, relevance=60, type_match=90, attractiveness=80)
        outline = gates.OutlineReviewResult(**self.common, completeness=50, structure_match=90,
                                            research_reference=80, image_marks=100)
        for schema, reply in [(gates.TitleReviewResult, title), (gates.OutlineReviewResult, outline)]:
            result, invoke = self.gate(schema, reply)
            self.assertFalse(result["passed"])
            self.assertEqual(invoke.call_count, 2)
            with self.assertRaises(ValidationError):
                schema.model_validate({**reply.model_dump(), "score": -10})
        for invalid in [[""], ["A", "A", "B"], ["A", "B", "X" * 31]]:
            with self.assertRaises(ValidationError):
                TitleList(titles=invalid)

    def test_short_outline_decision_distinguishes_coverage_from_blockers(self):
        state = dict(topic="如何测量两只杯子的容量", article_style="popular_science",
                     word_count=500, outline="## 准备与标记\n## 读数与比较")
        coverage = "两节分别列出准备与读数，涵盖操作和对比。"
        blocker = dict(point=1, where="读数与比较", why="未说明从哪条刻度读数",
                       expected="指定读数参照，给实际测量留位置")
        for problems in [[], [blocker]]:
            with self.subTest(problems=problems), patch.object(gates, "bind_structured_output") as bind:
                standard, short = Mock(), Mock()
                bind.side_effect = lambda schema, **_: short if schema is gates.ShortOutlineReview else standard
                short.invoke.return_value = gates.ShortOutlineReview(coverage=coverage, blocking_issues=problems)
                node = gates.make_quality_gate_node("主编", lambda s: s["outline"], gates.OutlineReviewResult)
                result = node(state)["review_result"]
                self.assertEqual(result["passed"], not problems)
                self.assertEqual(result["review_opinions"], problems)
                self.assertEqual(result["pass_reasons"], [] if problems else [coverage])
                self.assertIn(state["outline"], short.invoke.call_args.args[0][1][1])
                short.invoke.assert_called_once()
                standard.invoke.assert_not_called()

    def test_planning_revisions_receive_last_draft_and_opinions(self):
        for module, build, key, previous in [
            (title_graph, title_graph.build_title_graph, "titles", ["第一稿", "保留这一项", "第三稿"]),
            (outline_graph, outline_graph.build_outline_graph, "outline", "## 保留这一项"),
        ]:
            builders = {}
            def capture(*args, output_key, task_builder, **kwargs):
                builders[output_key] = task_builder
                return lambda s: {}
            with patch.object(module, "make_output_node", side_effect=capture):
                build()
            prompt = builders[key]({key: previous, "review_feedback": "调整第二项的例子"})
            self.assertIn("保留这一项", prompt)
            self.assertIn("调整第二项的例子", prompt)

    def test_trim_cannot_delete_scope_to_fit_budget(self):
        caveat = "只测试了缓存已经预热的机器，首次打开时的性能仍然未知。"
        state = dict(content="# 实验\n## 测量\n" + "记录本次启动过程。" * 28 + caveat, word_count=100)
        original = state["content"]
        with patch("src.blog_agent.agent.nodes.body_length.chat", return_value="# 实验\n## 测量\n本轮启动时间缩短。") as writer:
            self.assertEqual(agent_service.rewrite_to_word_range(state), (False, False))
        self.assertEqual(state["content"], original)
        self.assertEqual(writer.call_count, 2)
        self.assertIn(caveat, writer.call_args.args[0])

    def test_length_edit_restores_exact_code_caveat_and_headings_after_retry(self):
        import re

        caveat = "本例仅测量本地文件，不代表网络读写性能[S1]。"
        code = "```python\nfor item in ['  A', 'B, C']:\n    print(repr(item))\n```"
        source = "# 文件读取\n\n## 操作\n\n" + code + "\n\n" + caveat + "\n\n" + "重复说明。" * 70
        state = dict(selected_title="文件读取", content=source, word_count=100, outline="## 操作")
        def rewrite(prompt, **_):
            markers = re.findall(r"^(⟦原文\d+⟧) 还原为：", prompt, flags=re.M)
            self.assertEqual(len(markers), 4)
            self.assertIn(code, prompt)
            self.assertIn(caveat, prompt)
            if rewrite.calls == 0:
                rewrite.calls += 1
                return "\n\n".join([*markers, "可缩减。" * 65])
            return "\n\n".join([markers[0], markers[1], code, markers[3], "运行时可核对实际输出。"])
        rewrite.calls = 0
        with patch("src.blog_agent.agent.nodes.body_length.chat", side_effect=rewrite) as writer:
            self.assertEqual(agent_service.rewrite_to_word_range(state), (True, True))
        self.assertEqual(writer.call_count, 2)
        self.assertEqual(state["content"], "\n\n".join(["# 文件读取", "## 操作", code, caveat, "运行时可核对实际输出。"]))

    def test_short_factual_edit_can_expand_388_char_draft_at_its_original_position(self):
        import json
        from src.blog_agent.agent.nodes import body_length

        fact = "记录的两个样本仅代表本次测量[S1]。"
        code = "```python\nfor x in ('a?b', 'c!'):\n    print(x)\n```"
        outline = "## 操作\n## 观察"
        base = "# 观测\n\n## 操作\n\n" + code + "\n\n## 观察\n\n" + fact + "\n\n说明中的 `a?b` 保持原样。"
        prefix = "描述输入和结果的方法。"
        filler = (prefix * 40)[:388 - gates.count_chars(base)]
        original = base + "\n\n" + filler
        self.assertEqual(gates.count_chars(original), 388)
        state = dict(topic="如何记录测量结果", article_style="popular_science", selected_title="观测",
                     content=original, word_count=500, outline=outline)
        addition = "可把记录并排放置，分别读出两项，再回头对照原记录。"
        def edit(messages):
            menu = json.loads(messages[1][1].rsplit("\n", 1)[1])
            slot = next(i for i, mode, value in menu if value == fact and mode == "段后追加")
            self.assertFalse(any(mode == "替换" and ("`" in value or "[S1]" in value) for _, mode, value in menu))
            return body_length.PassageEdits(edits=[dict(slot=slot, text=addition)])
        with patch.object(body_length, "bind_structured_output") as bind, patch.object(body_length, "chat") as chat:
            bind.return_value.invoke.side_effect = edit
            self.assertEqual(body_length.rewrite_to_word_range(state), (True, True))
            bind.return_value.invoke.assert_called_once()
            chat.assert_not_called()
        self.assertEqual(state["content"], original.replace(fact, fact + "\n\n" + addition))

    def test_science_length_expansion_requires_an_existing_evidence_address(self):
        from src.blog_agent.agent.nodes import body_length

        original = "# 观测\n\n## 观察\n\n可将两组记录放在一起。"
        source = dict(id="S1", url="https://example.org/notes", excerpt="第一组记录位于左侧，第二组记录位于右侧。")
        for address, accepted in [("", False), ("@S1.9", False), ("@S2.1", False), ("@S1.1", True)]:
            state = dict(topic="如何比较两组记录", article_style="popular_science", selected_title="观测",
                         content=original, word_count=125, outline="## 观察", evidence_sources=[source])
            replacement = "比较时先看左侧的第一组记录，再看右侧的第二组记录。"
            with self.subTest(address=address), patch.object(body_length, "bind_structured_output") as bind:
                bind.return_value.invoke.return_value = body_length.PassageEdits(edits=[
                    dict(slot=1, text=replacement, evidence_address=address)])
                self.assertEqual(body_length.rewrite_to_word_range(state), (accepted, accepted))
                self.assertIn("@S1.1", bind.return_value.invoke.call_args.args[0][1][1])
                if accepted:
                    self.assertIn(replacement[:-1] + "[S1]。", state["content"])
                else:
                    self.assertEqual(state["content"], original)
                    self.assertEqual(bind.return_value.invoke.call_count, 2)
        state.update(content=original, evidence_questions=[{"url": "https://example.org/missing"}])
        with patch.object(body_length, "bind_structured_output") as bind:
            self.assertEqual(body_length.rewrite_to_word_range(state), (False, False))
            self.assertEqual(state["content"], original)
            bind.return_value.invoke.assert_not_called()

    def test_photo_size_fallback_and_zero_relevance(self):
        photo = dict(src={"medium": "https://images.pexels.com/example.jpg"}, alt="a microscope")
        response = Mock(status_code=200)
        response.json.return_value = {"photos": [None, {}, photo]}
        with patch("src.blog_agent.clients.image_client.settings.pexels_api_key", "offline"), patch(
            "src.blog_agent.clients.image_client.http.get", return_value=response,
        ):
            candidates = ImageClient().search_pexels("microscope")
        self.assertEqual(ImageClient.select_best_image(candidates, "microscope"), photo["src"]["medium"])
        self.assertIsNone(ImageClient.select_best_image(candidates, "beach"))
        self.assertEqual(ImageClient.select_best_image([{"url": "match", "alt": "显微镜下观察样品"}], "显微镜"), "match")

    def test_outline_image_request_rejects_missing_or_incomplete_marker(self):
        result, invoke = self.gate(gates.OutlineReviewResult, None,
                                   {"outline": "## 阅读\n<!-- 配图：书本", "need_image": True})
        self.assertFalse(result["passed"])
        self.assertIn("有效配图标记", str(result["review_opinions"]))
        invoke.assert_not_called()
