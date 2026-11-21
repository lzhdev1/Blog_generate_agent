"""Detached search replies and model responses; run the production research graph and quality gate."""
import json
import os
import unittest
from unittest.mock import Mock, patch

import httpx
from langchain_core.messages import AIMessage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("LLM_API_KEY", "offline")
os.environ.setdefault("LLM_BASE_URL", "http://127.0.0.1:9/v1")

from src.blog_agent.agent.evidence import (MAX_SOURCES, cited_sources, evidence_issues, export_with_sources,
                                           personal_reflection, source_records, unsupported_outline_measurements)
from src.blog_agent.agent.agents import source_questions
from src.blog_agent.agent.graphs import content_graph, supervisor_graph
from src.blog_agent.agent.nodes import quality_gate, react_model
from src.blog_agent.agent.nodes.output_node import collect_search_results
from src.blog_agent.agent.tools import search_tool, source_page
from src.blog_agent.db.models import BlogTask, TaskStatus
from src.blog_agent.db.session import Base
from src.blog_agent.service import agent_service


PAGES = [
    {"name": "年度访问公告", "url": "https://museum.example/annual", "siteName": "博物馆",
     "summary": "预约开放日当天有123位访客，数据只统计上午。" + "余" * 4050},
    {"name": "闭馆通知", "url": "https://museum.example/hours", "snippet": "星期一全天闭馆。"},
]


def reply(pages):
    return httpx.Response(200, json={"code": 200, "data": {"webPages": {"value": pages}}})


class SourceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(search_tool.settings, "bocha_api_key", "fixture"))

    def test_personal_reflection_keeps_explicit_research_requests(self):
        state = {"article_style": "note", "topic": "个人笔记：睡前写下一件小事"}
        self.assertTrue(personal_reflection(state))
        self.assertFalse(personal_reflection({**state, "extra_requirements": "请结合论文做对比"}))
        self.assertFalse(personal_reflection({**state, "article_style": "technical"}))

    def test_factual_outline_cannot_lock_unverified_measurements_into_headings(self):
        source = {"title": "观测", "url": "https://example.org/geometry", "excerpt": "inclination of 5.1 degrees"}
        state = {"article_style": "popular_science", "messages": [
            {"role": "tool", "search_result": {"status": "ok", "sources": [source]}}]}
        headings = [("##", "观察 5.1 度的夹角"), ("##", "5.9° 的偏移"), ("##", "三个观测步骤")]
        self.assertEqual(unsupported_outline_measurements(state, headings), ["5.9° 的偏移"])
        self.assertEqual(unsupported_outline_measurements({**state, "topic": "假设偏移为 5.9 度"}, headings), [])

    def test_small_spelled_measurements_match_digits_without_truncating_larger_numbers(self):
        from src.blog_agent.agent.evidence import _quantities
        self.assertIn(("3", "度"), _quantities("a three-degree tilt"))
        self.assertIn(("9", "%"), _quantities("nine percent"))
        for text in ("twenty-three degrees", "one hundred and three degrees", "zero point three degrees"):
            self.assertNotIn(("3", "度"), _quantities(text))

    def test_results_are_bounded_per_item_and_status_cannot_become_a_source(self):
        with patch.object(search_tool.http, "post", return_value=reply(PAGES)):
            found = search_tool.web_search.invoke({"query": "预约"})
        raw = {"role": "tool", "search_result": found}
        records = source_records([raw, raw])
        self.assertEqual([s["id"] for s in records], ["S1", "S2"])
        self.assertEqual(records[1]["excerpt"], "星期一全天闭馆。")
        self.assertLessEqual(len(records[0]["excerpt"]), 360)
        with patch.object(search_tool.http, "post", return_value=httpx.Response(429, text="supplier debug detail")):
            failed = search_tool.web_search.invoke({"query": "开放"})
        with patch.object(search_tool.http, "post", return_value=reply([])):
            self.assertEqual(search_tool.web_search.invoke({"query": "开放"})["status"], "empty")
        self.assertEqual(failed, {"status": "unavailable", "reason": "http_429", "sources": []})
        presented = collect_search_results({"messages": [
            {"role": "tool", "content": "internal-error", "search_result": failed},
            {"role": "assistant", "search_result": found}, raw,
        ]})
        self.assertIn("星期一全天闭馆", presented)
        self.assertNotIn("internal-error", presented)
        self.assertNotIn("http_429", presented)

    def test_research_replacement_keeps_source_identity_and_exports_only_cited_references(self):
        def message(page):
            return {"role": "tool", "search_result": {"status": "ok", "sources": [page]}}
        first = {"title": "甲", "url": "https://museum.example/tickets", "excerpt": "预约。"}
        other = {"title": "乙", "url": "https://museum.example/hours", "excerpt": "九时开馆。"}
        records = source_records([message(first)])
        replaced = source_records([message(other)], known_ids={first["url"]: records[0]["id"]})
        self.assertEqual(replaced[0]["id"], "S2")
        merged = source_records([message(first)], replaced, {first["url"]: "S1"})
        body = "参观需预约[S1]。"
        public, = cited_sources(body, merged)
        self.assertEqual(public, {"id": "S1", "title": "甲", "url": first["url"]})
        self.assertIn(first["url"], export_with_sources(body, merged))
        self.assertNotIn(other["url"], export_with_sources(body, merged))

    def test_page_snippet_precedes_provider_summary_and_summary_only_is_labelled(self):
        page = {**PAGES[0], "snippet": "上午开放时段只接待预约访客。"}
        with patch.object(search_tool.http, "post", return_value=reply([page, PAGES[0]])):
            records = search_tool.web_search.invoke({"query": "预约"})["sources"]
        self.assertEqual(records[0]["excerpt"], page["snippet"])
        self.assertTrue(records[1]["excerpt"].startswith("【检索摘要】"))

    def test_unfulfilled_reader_choice_and_relevant_official_page_precede_unrelated_hits(self):
        noise = {"url": "https://agency.gov/unrelated", "title": "Annual offices", "excerpt": "Opening hours"}
        first = {"url": "https://agency.gov/manual", "title": "Daily sensor calibration", "excerpt": "Sample readings"}
        selected = "https://publisher.example/measurement"
        records = {r["url"]: r for r in (noise, first)}
        urls = source_page.select_pages(records, [selected, selected, "http://ignored.example"],
                                        ["daily sensor calibration"])
        self.assertEqual(urls, [selected, first["url"], noise["url"]])

    def test_page_passage_with_exact_term_survives_a_long_page_with_generic_hits(self):
        noise = [f"Signal processing in sensor {i} estimates light and dark conditions for an outdoor sensor."
                 for i in range(8)]
        exact = "Dark current is measured when the detector is shielded from incoming light."
        result = source_page._excerpt([*noise, exact], "light signal sensor dark current")
        self.assertIn(exact, result)

    def test_each_question_gets_its_own_page_read_unless_original_excerpt_covered_it(self):
        url = "https://agency.example/manual"
        prior = {"id": "S1", "url": url, "origin": "page", "excerpt": "The sensor outputs a new reading every hour."}
        questions = [
            dict(question="when", url=url, keywords="outputs reading hour", existing_quote=prior["excerpt"]),
            dict(question="how", url=url, keywords="convert reading voltage", existing_quote=""),
            dict(question="why", url=url, keywords="reduces interference", existing_quote="not on the page"),
        ]
        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = source_questions.SourceQuestions(items=questions)
        with patch.object(source_questions, "read_web_sources") as reader:
            read = reader.invoke
            read.return_value = {"status": "empty", "sources": []}
            pages, trace = source_questions.research_questions(model, {"topic": "测量"}, [prior], {})
        self.assertEqual([q["status"] for q in trace], ["existing", "unavailable", "unavailable"])
        self.assertEqual([c.args[0]["keywords"] for c in read.call_args_list],
                         ["convert reading voltage", "reduces interference"])
        self.assertEqual(len(pages), 2)

    def test_missing_question_url_searches_once_then_opens_the_discovered_page(self):
        url = "https://agency.example/light"
        query = "measure emitted sensor light"
        model = Mock()
        model.with_structured_output.return_value.invoke.return_value = source_questions.SourceQuestions(items=[
            dict(question="怎样测量", url="", keywords=query, existing_quote="")])
        with patch.object(source_questions, "web_search") as search, patch.object(source_questions, "read_web_sources") as reader:
            search.invoke.return_value = {"sources": [{"url": url, "title": "Sensor light", "excerpt": "measuring light"}]}
            reader.invoke.return_value = {"sources": [{"url": url, "excerpt": "Original readings.", "origin": "page"}]}
            opened, trace = source_questions.research_questions(model, {"topic": "观测"}, [], {})
        search.invoke.assert_called_once_with({"query": query})
        reader.invoke.assert_called_once_with({"urls": [url], "keywords": query})
        self.assertEqual((len(opened), trace[0]["url"], trace[0]["status"]), (1, url, "opened"))

    def test_extractor_upgrade_refreshes_only_saved_question_then_keeps_version_and_id(self):
        url = "https://agency.example/light"
        row = {"url": url, "origin": "page", "id": "S8", "excerpt": "Initial description."}
        q = {"url": url, "keywords": "original search words", "status": "opened"}
        state = {"evidence_sources": [row], "evidence_questions": [q, q]}
        with patch.object(source_questions, "read_web_sources") as reader:
            reader.invoke.return_value = {"status": "ok", "sources": [{**row, "excerpt": "Direct explanation."}]}
            update = source_questions.refresh_saved_questions(state)
            self.assertEqual(source_questions.refresh_saved_questions({**state, **update}), {})
            reader.invoke.assert_called_once_with({"urls": [url], "keywords": "original search words"})
        self.assertEqual(update["evidence_sources"][0]["id"], "S8")
        self.assertIn("Direct explanation.", update["evidence_sources"][0]["excerpt"])

    def test_requested_site_limits_search_to_that_domain_and_its_subdomains(self):
        unrelated = {**PAGES[0], "url": "https://museum.example.unrelated.example/summary"}
        official = {**PAGES[1], "url": "https://docs.museum.example/open"}
        with patch.object(search_tool.http, "post", return_value=reply([unrelated, official])) as request:
            result = search_tool.web_search.invoke({"query": "开放", "site": "Museum.EXAMPLE"})
            self.assertEqual(request.call_args.kwargs["json"]["include"], "museum.example")
            self.assertEqual([p["url"] for p in result["sources"]], [official["url"]])
            invalid = search_tool.web_search.invoke({"query": "开放", "site": "https://museum.example/x"})
            self.assertEqual(invalid["reason"], "invalid_site")
            request.assert_called_once()

    def test_supplement_same_cited_url_adds_new_evidence_without_losing_old_passage(self):
        prior = [{"id": "S7", "title": "参观公告", "url": "https://museum.example/open",
                  "excerpt": "需提前预约。"}]
        state = {"article_style": "technical", "content": "当日上午有123位访客[S7]。"}
        self.assertTrue(evidence_issues({**state, "evidence_sources": prior}))
        fresh = {**prior[0], "excerpt": "当日上午有123位访客。"}
        message = {"role": "tool", "search_result": {"status": "ok", "sources": [fresh]}}
        records = source_records([message], prior, content=state["content"])
        self.assertEqual([record["id"] for record in records], ["S7"])
        self.assertIn(prior[0]["excerpt"], records[0]["excerpt"])
        self.assertFalse(evidence_issues({**state, "evidence_sources": records}))
        self.assertEqual(source_records([message], records, content=state["content"]), records)

    def test_full_dossier_allows_a_supplement_and_preserves_previously_cited_material(self):
        prior = [{"id": f"S{n}", "url": f"https://museum.example/files/{n}", "title": str(n), "excerpt": "预约。"}
                 for n in range(1, MAX_SOURCES + 1)]
        new = {"url": "https://museum.example/new", "title": "新开放日", "excerpt": "五月开始。"}
        result = source_records([{"role": "tool", "search_result": {"status": "ok", "sources": [new]}}],
                                existing=prior, content="参见最后的记录[S16]。")
        self.assertEqual(len(result), MAX_SOURCES)
        self.assertIn(prior[-1], result)
        self.assertEqual(result[-1]["url"], new["url"])

    def test_supplement_upgrades_legacy_evidence_and_preserves_full_page_passages(self):
        url = "https://museum.example/observation"
        saved = {"id": "S4", "url": url, "title": "检索记录", "excerpt": "未由原页证实"}

        def supplement(prior, origin, excerpt):
            row = {"url": url, "title": "原文", "origin": origin, "excerpt": excerpt}
            message = {"role": "tool", "search_result": {"status": "ok", "sources": [row]}}
            return source_records([message], prior, content="来源[S4]。")

        page = supplement([saved], "page", "甲" * 1250)
        self.assertEqual((page[0]["id"], page[0]["origin"], page[0]["excerpt"]), ("S4", "page", "甲" * 1250))
        self.assertEqual(supplement(page, "discovery", saved["excerpt"]), page)
        second = supplement(page, "page", "乙" * 1450)
        self.assertIn("甲" * 1250, second[0]["excerpt"])
        self.assertIn("乙" * 1450, second[0]["excerpt"])
        self.assertEqual(supplement(second, "page", "乙" * 1450), second)

    def test_reference_checks_distinguish_observation_from_code_and_personal_narrative(self):
        source = {"id": "S1", "title": "报告", "url": "https://museum.example/data", "excerpt": "当日有123位访客。"}
        state = {"article_style": "technical", "evidence_sources": [source]}
        self.assertFalse(evidence_issues({**state, "content": "当日有123位访客[S1]。"}))
        for bad in ("当日有123位访客[S2]。", "当日有123位访客。另一节写参观[S1]。",
                    "当日增长123%[S1]。", "到访记录[S1]。详见 https://museum.example/other"):
            with self.subTest(bad=bad):
                self.assertTrue(evidence_issues({**state, "content": bad}))
        self.assertFalse(evidence_issues({"article_style": "prose", "content": "我留下参观笔记。"}))
        self.assertFalse(evidence_issues({"article_style": "note",
                                         "content": "示例\n```text\n研究显示 30% [S99]\n```\n"}))
        self.assertTrue(evidence_issues({"article_style": "note", "content": "研究显示有123位访客。"}))

    def test_personal_measurement_limit_preserves_adjacent_assertions(self):
        def issues(body, style="note"):
            return evidence_issues({"article_style": style, "content": body, "evidence_sources": []})

        for body in ("我没有计时，也没有足够数据证明效率提高了30%。",
                     "我没有足够证据断定效率提高了30%。",
                     "我无法据此认定耗时降低了20%。",
                     "我没有得出“效率提高了30%”这样的结论。",
                     "这次我无法据此断言效率提升30%。"):
            with self.subTest(body=body):
                self.assertFalse(issues(body))
        for body in ("我测过，效率提高了30%。",
                     "我没有足够证据断定效率提高了30%，但是耗时下降了20%。",
                     "我不是不能断定效率提高了30%。",
                     "我不是没有证据证明效率提高了30%。",
                     "我没有足够数据证明效率提高了30%，但耗时确实下降了20%。",
                     "耗时下降了20%，我无法证明效率提高了30%。",
                     "我无法证明效率提高了30%但实际耗时减少了20%。",
                     "我读到一份报告，作者没有证据证明效率提高了30%。"):
            with self.subTest(body=body):
                self.assertTrue(issues(body))
        self.assertTrue(issues("我没有计时，也没有足够数据证明效率提高了30%。", style="technical"))

    def test_editorial_reference_sample_pairs(self):
        # Fixed examples for the source checks. "Pass" still goes to the semantic editor.
        yearly = {"id": "S1", "url": PAGES[0]["url"], "title": "博物馆访问公告",
                  "excerpt": "预约开放日当天有123位访客，数据只统计上午。"}
        hours = {"id": "S2", "url": PAGES[1]["url"], "title": "开放时间", "excerpt": "星期一全天闭馆。"}
        bench = {"id": "S3", "url": "https://lab.example/cache", "title": "缓存实验",
                 "excerpt": "预热设备的启动耗时降低30%，首次启动未测。"}
        english = {"id": "S4", "url": "https://lab.example/visits", "title": "Attendance",
                   "excerpt": "On the open day the museum recorded 123 visitors in the morning."}
        cases = [
            ("双来源科普", "popular_science", [yearly, hours], "预约开放日上午有123位访客[S1]。本馆周一闭馆[S2]。", True),
            ("保留条件的技术测评", "technical", [bench], "预热后的启动耗时降低30%[S3]。首次启动未测。", True),
            ("引用英文原始材料", "essay", [english], "开放日上午有123位访客[S4]。", True),
            ("个人散文", "prose", [], "傍晚离开庭院时，我记住了风经过树梢的声音。", True),
            ("仅标题附来源", "essay", [hours], "# 开放时间[S2]\n本文梳理了一些想法。", False),
            ("来源清单脱离论断", "technical", [hours], "这篇文章讨论参观。\n资料来源：[S2]", False),
            ("同段的另句来源", "technical", [yearly], "开放日上午有123位访客。开放日上午的记录已归档[S1]。", False),
            ("只是相同数字和单位", "technical", [bench], "研究显示香水销量降低30%[S3]。", False),
            ("已有依据不能覆盖另一条事实", "popular_science", [yearly], "本馆周一闭馆。预约开放日上午有123位访客[S1]。", False),
            ("标题里的数字与正文脱节", "essay", [yearly], "# 访客增长80%\n预约开放日上午有123位访客[S1]。", False),
            ("虚构限流借口", "essay", [], "调研员说资料已经核查完毕。", False),
            ("个人笔记引用了统计", "note", [], "据统计，活动带来了123位访客。", False),
        ]
        with patch.object(quality_gate, "bind_structured_output") as editor, patch.object(
            quality_gate.settings, "enable_review", True
        ):
            editor.return_value.invoke.return_value = quality_gate.ReviewResult(
                passed=True, score=94, pass_reasons=["完成复核"],
                dimension_scores=dict(outline_compliance=94, relevance=94, style_match=94, research_usage=94, logic_flow=94),
            )
            gate = quality_gate.make_quality_gate_node("编辑", supervisor_graph._build_content_review_task)
            for description, style, sources, body, should_pass in cases:
                with self.subTest(description=description):
                    report = gate({"article_style": style, "content": body, "evidence_sources": sources,
                                   "word_count": 100})["review_result"]
                    self.assertEqual(report["passed"], should_pass, report)
            self.assertEqual(editor.return_value.invoke.call_count, sum(c[-1] for c in cases))

    def run_manuscript(self, provider, sentence, expected):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        with sessions.begin() as db:
            task = BlogTask(topic="博物馆开放情况", selected_title="开放情况", article_style="technical",
                            outline="## 参观", outline_confirmed=True, word_count=100)
            db.add(task)
            db.flush()
            task_id = task.id
        planner = Mock()
        planner.bind_tools.return_value.invoke.side_effect = [
            AIMessage(content="", tool_calls=[{"id": "search", "name": "web_search", "args": {"query": "开放"}}]),
            AIMessage(content="结束"),
        ]
        summary = Mock()
        summary.invoke.return_value = AIMessage(content="模型只给出检索方向。")
        planned = summary.with_structured_output.return_value.invoke
        planned.return_value = source_questions.SourceQuestions(items=[
            dict(question="有多少人到馆", url=PAGES[0]["url"], keywords="统计 到馆人数",
                 existing_quote="博物馆的预约开放日当天有123位访客，此数据只统计上午的到馆人数。")])
        writer = Mock()
        body = "# 开放情况\n\n## 参观\n" + sentence
        writer.invoke.return_value = AIMessage(content=body)
        editor = Mock()
        editor.invoke.return_value = quality_gate.ReviewResult(
            passed=True, score=94, pass_reasons=["逐项核对来源"],
            claim_checks=[dict(item=1, basis="S1", quote="@S1.1")],
            dimension_scores=dict(outline_compliance=94, relevance=94, style_match=94, research_usage=94, logic_flow=94),
        )
        with patch.object(react_model, "get_chat_model", return_value=planner), patch.object(
            content_graph, "get_chat_model", side_effect=lambda role, **kw: writer if role == "writer" else summary,
        ), patch.object(quality_gate, "bind_structured_output", return_value=editor):
            graph = content_graph.build_content_graph()
            gate = quality_gate.make_quality_gate_node("审稿", supervisor_graph._build_content_review_task)
        def fetch_page(request, **kwargs):
            html = ("<title>开放公告</title><article><p>博物馆的预约开放日当天有123位访客，此数据只统计上午的到馆人数。</p></article>"
                    if request.url.path == "/annual" else "<title>开放时间</title><p>星期一全天闭馆；本周其余日期开放时段以馆内当天公告为准。</p>")
            return httpx.Response(200, request=request, headers={"Content-Type": "text/html; charset=utf-8"}, text=html)

        with patch.object(source_page, "_public_address", return_value="93.184.216.34"), patch.object(
            source_page.http, "send", side_effect=fetch_page
        ), patch.object(search_tool.http, "post", return_value=provider), patch.object(
            agent_service, "SessionLocal", sessions
        ), patch.object(agent_service.settings, "max_review_rounds", 0), patch.object(
            quality_gate.settings, "enable_review", True
        ), patch.object(agent_service, "_CONTENT_GRAPH", graph), patch.object(agent_service, "_CONTENT_GATE", gate):
            agent_service._run_content_stage(task_id)
        with sessions() as db:
            task = db.get(BlogTask, task_id)
            self.assertEqual(task.status, expected, task.error)
            self.assertEqual(task.content, body)
            if expected == TaskStatus.COMPLETED:
                self.assertEqual(task.evidence_sources[0]["url"], PAGES[0]["url"])
                self.assertEqual(task.evidence_sources[0]["origin"], "page")
                self.assertIn("到馆人数", task.evidence_sources[0]["excerpt"])
                self.assertIn(PAGES[0]["url"], planned.call_args.args[0][1][1])
                for model in (writer, editor):
                    self.assertIn(PAGES[0]["url"], model.invoke.call_args.args[0][1][1])
            else:
                self.assertFalse(task.is_public)
                self.assertIn("待核实", task.error)
                self.assertTrue(json.loads(task.review_feedback)["need_re_research"])
                editor.invoke.assert_not_called()
        return (planned.call_args or summary.invoke.call_args).args[0][1][1]

    def test_grounded_article_completes_with_reviewable_originals(self):
        self.run_manuscript(reply(PAGES), "预约开放日上午有123位访客[S1]。", TaskStatus.COMPLETED)

    def test_invented_count_or_reference_keeps_the_draft_private(self):
        self.run_manuscript(reply(PAGES), "到访人数是999位访客[S1]。来源 https://museum.example/fake", TaskStatus.FAILED)

    def test_search_429_is_not_material_and_does_not_approve_factual_copy(self):
        text = self.run_manuscript(httpx.Response(429, text="sensitive provider message"), "参观人数有待核实。", TaskStatus.FAILED)
        self.assertNotIn("sensitive provider message", text)
        self.assertNotIn("http_429", text)
