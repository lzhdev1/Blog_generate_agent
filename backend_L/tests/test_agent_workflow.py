"""离线回归：真实子图与数据库会话，只替换模型和外部图片服务。"""
import json
import os
import unittest
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("LLM_API_KEY", "offline")
os.environ.setdefault("LLM_BASE_URL", "http://localhost")

from src.blog_agent.agent.agents.formatter import format_markdown
from src.blog_agent.agent.agents.writer_prompts import CONTENT_MARKER, THOUGHTS_MARKER
from src.blog_agent.agent.graphs import content_graph, outline_graph, supervisor_graph, title_graph
from src.blog_agent.agent.nodes import quality_gate, react_model
from src.blog_agent.agent.nodes.react_tools import make_react_tools_node
from src.blog_agent.agent.state import AgentState
from src.blog_agent.db.models import BlogTask, TaskStatus
from src.blog_agent.db.session import Base
from src.blog_agent.service import agent_service


class AgentWorkflowTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine)
        self.addCleanup(engine.dispose)
        self.enterContext(patch.object(agent_service, "SessionLocal", self.sessions))
        self.enterContext(patch.object(agent_service.settings, "max_review_rounds", 1))
        self.body = "# 我的标题\n\n## 小节\n" + "正" * 194
        with self.sessions.begin() as db:
            task = BlogTask(topic="选题", selected_title="我的标题", outline="## 小节",
                            outline_confirmed=True, article_style="custom",
                            article_style_custom="写给实习工程师", word_count=200,
                            status=TaskStatus.RESEARCHING_CONTENT)
            db.add(task)
            db.flush()
            self.task_id = task.id

    def install_content_graph(self, bodies):
        writer = Mock()
        writer.invoke.side_effect = [AIMessage(content=text) for text in bodies]
        researcher = Mock()
        researcher.invoke.return_value = AIMessage(content="可复用的资料")
        def model(role, **kwargs):
            return writer if role == "writer" else researcher

        with patch.object(content_graph, "get_chat_model", side_effect=model), patch.object(
            content_graph, "make_react_model_node", return_value=lambda s: {"messages": []},
        ):
            graph = content_graph.build_content_graph()
        self.enterContext(patch.object(agent_service, "_CONTENT_GRAPH", graph))
        return writer, researcher

    def test_revision_reuses_research_and_preserves_plan(self):
        first = THOUGHTS_MARKER + "\n写作计划\n" + CONTENT_MARKER + "\n" + self.body
        writer, researcher = self.install_content_graph([first, self.body + "修订"])
        failed = {"passed": False, "review_opinions": [{"where": "末段", "why": "重复", "expected": "精简"}]}
        accepted = {"passed": True, "score": 92}
        gate = Mock(side_effect=[{"review_result": failed}, {"review_result": accepted}])
        with patch.object(agent_service, "_CONTENT_GATE", gate), patch.object(
            agent_service, "format_markdown", wraps=self.assert_formatting_status,
        ):
            agent_service._run_content_stage(self.task_id)
        with self.sessions() as db:
            saved = db.get(BlogTask, self.task_id)
            self.assertEqual(saved.status, TaskStatus.COMPLETED)
            self.assertEqual(saved.writing_thoughts, "写作计划")
            self.assertEqual(saved.formatted_content, self.body + "修订")
            self.assertEqual(json.loads(saved.review_feedback), accepted)
        researcher.invoke.assert_called_once()
        revision = writer.invoke.call_args.args[0][1][1]
        for text in ["写给实习工程师", "精简", self.body]:
            self.assertIn(text, revision)

    def assert_formatting_status(self, content):
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.FORMATTING)
            self.assertIsNone(task.formatted_content)
        return format_markdown(content)

    def test_rejected_draft_stops_before_formatting(self):
        self.install_content_graph([self.body, self.body])
        review = {"passed": False, "review_opinions": [{"where": "首段", "why": "数据错误", "expected": "更正"}]}
        with patch.object(agent_service, "_CONTENT_GATE", return_value={"review_result": review}), patch.object(
            agent_service, "format_markdown",
        ) as formatter:
            agent_service._run_content_stage(self.task_id)
        formatter.assert_not_called()
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertIn("数据错误", task.error)
            self.assertEqual(task.content, self.body)

    def test_reviewer_failure_keeps_the_unreviewed_draft_private(self):
        self.install_content_graph([THOUGHTS_MARKER + "写作计划" + CONTENT_MARKER + self.body])
        def unavailable(state):
            with self.sessions() as reader:
                task = reader.get(BlogTask, self.task_id)
                self.assertEqual((task.status, task.content), (TaskStatus.REVIEWING, self.body))
            raise RuntimeError("审稿服务暂时不可用")
        with patch.object(agent_service, "_CONTENT_GATE", side_effect=unavailable):
            agent_service._run_content_stage(self.task_id)
        with self.sessions() as reader:
            task = reader.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.content, self.body)
            self.assertEqual(task.writing_thoughts, "写作计划")
            self.assertEqual(task.content_research, "可复用的资料")
            self.assertIsNone(task.review_feedback)
            self.assertIsNone(task.formatted_content)
            self.assertFalse(task.is_public)

    def test_writer_failure_keeps_completed_research(self):
        writer, _ = self.install_content_graph([])
        writer.invoke.side_effect = RuntimeError("写手服务暂时不可用")
        agent_service._run_content_stage(self.task_id)
        with self.sessions() as reader:
            task = reader.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.content_research, "可复用的资料")
            self.assertIsNone(task.content)
            self.assertTrue(task.outline_confirmed)

    def test_partial_image_failure_keeps_approved_text(self):
        image_body = self.body + "\n<!-- 配图：示意图 -->"
        with self.sessions.begin() as db:
            db.get(BlogTask, self.task_id).need_image = True
        self.install_content_graph([image_body])
        with patch.object(agent_service, "_CONTENT_GATE", return_value={"review_result": {"passed": True}}), patch.object(
            agent_service.image_agent, "analyze_image_needs", return_value=[{"index": 0, "query_or_prompt": "diagram"}],
        ), patch.object(agent_service.image_agent.image_client, "fetch_all", return_value=[None]):
            agent_service._run_content_stage(self.task_id)
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertIn("0/1", task.progress)
            self.assertEqual(task.formatted_content, self.body)
            self.assertEqual(task.content, image_body)

    def test_gate_rejects_wrong_heading_without_model(self):
        with patch.object(quality_gate, "bind_structured_output") as model:
            gate = quality_gate.make_quality_gate_node("编辑", lambda s: "稿件")
            result = gate({"content": self.body, "selected_title": "其他标题", "word_count": 200})
        self.assertFalse(result["review_result"]["passed"])
        model.return_value.invoke.assert_not_called()

    def test_disabled_editor_keeps_hard_checks_and_saves_no_editor_report(self):
        self.install_content_graph([self.body])
        with patch.object(quality_gate.settings, "enable_review", False), patch.object(
            quality_gate, "bind_structured_output",
        ) as model:
            gate = quality_gate.make_quality_gate_node("编辑", lambda s: "稿件")
            self.assertFalse(gate({"content": ""})["review_result"]["passed"])
            with patch.object(agent_service, "_CONTENT_GATE", gate):
                agent_service._run_content_stage(self.task_id)
            model.return_value.invoke.assert_not_called()
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertIsNone(task.review_feedback)

    def test_editor_retries_only_malformed_output_and_never_marks_it_approved(self):
        with patch.object(quality_gate.settings, "enable_review", True), patch.object(
            quality_gate, "bind_structured_output",
        ) as model:
            gate = quality_gate.make_quality_gate_node("编辑", lambda s: "选题", quality_gate.TitleReviewResult)
            model.return_value.invoke.side_effect = [quality_gate.OutputParserException("bad JSON"), None]
            with self.assertRaisesRegex(ValueError, "未返回可解析"):
                gate({})
            self.assertEqual(model.return_value.invoke.call_count, 2)

    def test_research_turn_keeps_system_and_user_instructions(self):
        with patch.object(react_model, "get_chat_model") as model:
            model.return_value.invoke.return_value = AIMessage(content="完成")
            node = react_model.make_react_model_node("研究角色", lambda s: "用户选题")
            first = node({"messages": []})
            node(first)
        sent = model.return_value.invoke.call_args.args[0]
        self.assertEqual([m.content for m in sent], ["研究角色", "用户选题", "完成"])

    def test_fenced_code_and_decimal_are_verbatim(self):
        code = "```python\n#comment\n\n\n1.25\n<!-- 配图：例 -->\n```"
        self.assertEqual(format_markdown(code + "\n3.14"), code + "\n3.14")

    def install_planning_graphs(self, **overrides):
        outputs = {"titles": ["标题一", "标题二", "标题三"], "title_scores": [{"title": "标题一", "total": 8}],
                   "outline": "## 引言", "title_research": "标题资料", "outline_research": "大纲资料",
                   **overrides}
        def output(*args, output_key, **kwargs):
            def run(state):
                value = outputs[output_key]
                return {output_key: value(state) if callable(value) else value}
            return run

        for module in [title_graph, outline_graph]:
            self.enterContext(patch.object(module, "make_output_node", side_effect=output))
            self.enterContext(patch.object(module, "make_react_model_node", return_value=lambda s: {"messages": []}))
        self.enterContext(patch.object(agent_service, "_TITLE_GRAPH", title_graph.build_title_graph()))
        self.enterContext(patch.object(agent_service, "_OUTLINE_GRAPH", outline_graph.build_outline_graph()))
        return outputs

    def test_title_scorer_interruption_keeps_new_candidates_without_old_scores(self):
        with self.sessions.begin() as db:
            db.get(BlogTask, self.task_id).title_scores = '[{"title":"过期候选"}]'

        def unavailable(state):
            with self.sessions() as db:
                task = db.get(BlogTask, self.task_id)
                self.assertEqual(task.status, TaskStatus.GENERATING_TITLES)
                self.assertEqual(json.loads(task.titles), state["titles"])
                self.assertIsNone(task.title_scores)
            raise RuntimeError("评分中断")

        outputs = self.install_planning_graphs(title_scores=unavailable)
        agent_service._run_title_stage(self.task_id, "选题")
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual((task.status, task.error), (TaskStatus.FAILED, "评分中断"))
            self.assertEqual(task.title_research, outputs["title_research"])
            self.assertEqual(json.loads(task.titles), outputs["titles"])
            self.assertIsNone(task.title_scores)

    def test_invalid_new_title_candidates_never_become_author_handoff(self):
        self.install_planning_graphs(titles=["", "重复", "重复"])
        with patch.object(agent_service, "_TITLE_GATE", return_value={"review_result": {"passed": True}}):
            agent_service._run_title_stage(self.task_id, "选题")
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertIn("候选标题格式无效", task.error)

    def test_interrupted_planning_reviews_keep_unapproved_outputs(self):
        outputs = self.install_planning_graphs()
        def interrupted(state):
            raise RuntimeError("审稿中断")

        with patch.object(agent_service, "_TITLE_GATE", side_effect=interrupted):
            agent_service._run_title_stage(self.task_id, "选题")
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual((task.status, task.error), (TaskStatus.FAILED, "审稿中断"))
            self.assertEqual(json.loads(task.title_scores), outputs["title_scores"])
            self.assertEqual(json.loads(task.titles), outputs["titles"])
        with patch.object(agent_service, "_OUTLINE_GATE", side_effect=interrupted):
            agent_service._run_outline_stage(self.task_id, "标题一", False, "essay", None, None)
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual((task.status, task.error), (TaskStatus.FAILED, "审稿中断"))
            self.assertEqual(task.outline_research, outputs["outline_research"])
            self.assertEqual(task.outline, outputs["outline"])
            self.assertFalse(task.outline_confirmed)
            self.assertIsNone(task.formatted_content)

    def test_title_outline_handoffs_retain_artifacts_when_review_limit_is_reached(self):
        titles = self.install_planning_graphs()["titles"]
        opinions = [{"point": 1, "where": "第二项", "why": "重复", "expected": "换一个角度"}]
        rejected = {"review_result": {"passed": False, "review_opinions": opinions}}
        self.enterContext(patch.object(agent_service, "_TITLE_GATE", return_value=rejected))
        self.enterContext(patch.object(agent_service, "_OUTLINE_GATE", return_value=rejected))
        agent_service._run_title_stage(self.task_id, "选题")
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.TITLE_GENERATED)
            self.assertEqual(json.loads(task.titles), titles)
            self.assertIn("审核未通过", task.progress)
            self.assertEqual(json.loads(task.review_feedback), {**rejected["review_result"], "stage": "title"})
        agent_service._run_outline_stage(self.task_id, titles[1], False, "essay", None, "论证清晰")
        with self.sessions() as db:
            task = db.get(BlogTask, self.task_id)
            self.assertEqual(task.status, TaskStatus.OUTLINE_GENERATED)
            self.assertEqual(task.outline, "## 引言")
            self.assertFalse(task.outline_confirmed)
            self.assertIn("审核未通过", task.progress)
            self.assertEqual(json.loads(task.review_feedback), {**rejected["review_result"], "stage": "outline"})

    def test_unattended_graph_stops_at_rejection(self):
        review = {"passed": False, "review_opinions": []}
        with patch.object(supervisor_graph, "build_title_graph", return_value=lambda s: {"titles": ["标题"]}), patch.object(
            supervisor_graph, "build_outline_graph", return_value=lambda s: self.fail("不应生成大纲"),
        ), patch.object(supervisor_graph, "build_content_graph", return_value=lambda s: self.fail("不应撰写正文")), patch.object(
            supervisor_graph, "make_quality_gate_node", return_value=lambda s: {"review_result": review},
        ):
            result = supervisor_graph.build_supervisor_graph(max_review_rounds=0).invoke({"topic": "选题"})
        self.assertEqual(result["stage"], "failed")
        self.assertEqual(result["review_result"], review)
        self.assertEqual(result.get("review_count", 0), 0)

    def test_unattended_title_uses_aligned_scores_and_respects_explicit_selection(self):
        advance = supervisor_graph.make_stage_switch("outline")
        candidates = ["甲", "乙", "丙"]
        scores = [{"title": "乙", "accuracy": 9, "total": 8.3},
                  {"title": "甲", "accuracy": 7, "total": 9.5},
                  {"title": "丙", "accuracy": 9, "total": 8.3}]
        state = {"titles": candidates, "title_scores": scores}
        self.assertEqual(advance(state)["selected_title"], "乙")
        self.assertNotIn("selected_title", advance({**state, "selected_title": "丙"}))
        for bad in (scores[:2], [scores[0], scores[0], scores[2]], [*scores[:2], {**scores[2], "accuracy": 99}]):
            self.assertEqual(advance({**state, "title_scores": bad})["selected_title"], "甲")

    def test_planning_stays_within_the_original_question_and_genre(self):
        technical = {"topic": "读取表格", "article_style": "technical"}
        note = {"topic": "睡前记下一件小事", "article_style": "note"}
        with patch.object(quality_gate.settings, "enable_review", False), patch.object(quality_gate, "bind_structured_output"):
            titles = quality_gate.make_quality_gate_node("主编", lambda s: "题目", quality_gate.TitleReviewResult)
            outline = quality_gate.make_quality_gate_node("主编", lambda s: "提纲", quality_gate.OutlineReviewResult)
            for gate, state in [
                (titles, {**technical, "titles": ["为什么编号总是丢失？"]}),
                (outline, {**technical, "outline": "## 为什么解析总在静默中出错？"}),
                (titles, {**note, "titles": ["给大脑做一次极简卸载"]}),
                (outline, {**note, "outline": "## 如何缓解睡前焦虑"}),
            ]:
                self.assertFalse(gate(state)["review_result"]["passed"])
            for state in [{**technical, "titles": ["为什么编号不总是保留？", "为什么‘总会失败’是一种误解？"]},
                          {**technical, "topic": "为什么编号总是变短？", "titles": ["为何编号总是变短？"]},
                          {**note, "titles": ["今晚想记住的那件小事"]},
                          {**note, "purpose": "记录自己面对焦虑的选择", "titles": ["我想试着缓解焦虑"]}]:
                self.assertTrue(titles(state)["review_result"]["passed"])

    def test_unattended_single_candidate_has_its_own_review_and_cannot_bypass_a_gate(self):
        state = {"topic": "睡前写下小事", "article_style": "note", "force_review": True,
                 "titles": ["睡前的一张便签", "认知卸载的妙方", "改善失眠的方法"],
                 "review_result": {"passed": False, "review_opinions": []}}
        good = dict(selected_title="睡前的一张便签", passed=True, score=91, relevance=95,
                    type_match=92, attractiveness=83, pass_reasons=["围绕一件小事，未承诺干预效果"])
        for update, expected in [({}, True), ({"score": 70}, False), ({"selected_title": "模型新造的标题"}, False),
                                 ({"selected_title": "认知卸载的妙方"}, False), ({"pass_reasons": []}, False),
                                 ({"passed": False, "selected_title": "", "pass_reasons": []}, False)]:
            with self.subTest(update=update), patch.object(quality_gate, "bind_structured_output") as model:
                model.return_value.invoke.return_value = quality_gate.SingleTitleReviewResult(**{**good, **update})
                decision = quality_gate.review_one_title(state)
                self.assertEqual(decision["review_result"]["passed"], expected)
                self.assertEqual(decision.get("selected_title"), good["selected_title"] if expected else None)
                model.return_value.invoke.assert_called_once()
        with patch.object(quality_gate, "bind_structured_output") as model:
            decision = quality_gate.review_one_title({**state, "titles": ["缓解焦虑", "改善失眠", "治愈力"]})
            self.assertFalse(decision["review_result"]["passed"])
            model.assert_not_called()
        with patch.object(supervisor_graph, "build_title_graph", return_value=lambda s: {"titles": state["titles"]}), patch.object(
            supervisor_graph, "build_outline_graph", return_value=lambda s: {"outline": "## 便签"}), patch.object(
            supervisor_graph, "build_content_graph", return_value=lambda s: {"content": "短稿"}), patch.object(
            supervisor_graph, "make_quality_gate_node", return_value=lambda s: {"review_result": {"passed": s["stage"] != "title"}}), patch.object(
            quality_gate, "bind_structured_output",
        ) as model:
            model.return_value.invoke.return_value = quality_gate.SingleTitleReviewResult(**good)
            result = supervisor_graph.build_supervisor_graph(max_review_rounds=0).invoke({**state, "word_count": 100})
            self.assertEqual((result["stage"], result["selected_title"]), ("done", good["selected_title"]))
            model.return_value.invoke.assert_called_once()

    def test_supervisor_review_receives_only_current_research_even_after_a_retry(self):
        def stage(name, output):
            tool = Mock()
            tool.name = "web_search"
            tool.invoke.return_value = {"status": "ok", "sources": [{"url": f"https://example.org/{name}"}]}
            planner = Mock()
            planner.invoke.side_effect = [AIMessage(content="", tool_calls=[
                {"name": tool.name, "args": {}, "id": name},
            ]), AIMessage(content="资料足够")]
            with patch.object(react_model, "get_chat_model", return_value=planner):
                plan = react_model.make_react_model_node("研究", lambda s: name)
            child = StateGraph(AgentState)
            # The real child graphs keep research history when rewriting without another search.
            child.add_node("start_research", lambda s: {"messages": []})
            child.add_node("plan", plan)
            child.add_node("tools", make_react_tools_node([tool]))
            child.add_node("observe", plan)
            child.add_node("generate", lambda s: output)
            child.add_conditional_edges(START, lambda s: "generate" if s.get("review_count") else "start_research",
                                        ["generate", "start_research"])
            child.add_edge("start_research", "plan")
            child.add_edge("plan", "tools")
            child.add_edge("tools", "observe")
            child.add_edge("observe", "generate")
            child.add_edge("generate", END)
            return child.compile()

        seen = []
        def review(state):
            name = state["stage"]
            messages = state["messages"]
            self.assertEqual([m["role"] for m in messages], ["system", "user", "assistant", "tool", "assistant"])
            self.assertEqual(messages[1]["content"].splitlines()[0], name)
            self.assertEqual(messages[-2]["search_result"]["sources"][0]["url"], f"https://example.org/{name}")
            self.assertEqual(state["tool_traces"], [{"tool": "previous"}])
            seen.append(name)
            return {"review_result": {"passed": name != "outline" or seen.count(name) == 2}}

        with patch.object(supervisor_graph, "build_title_graph", return_value=stage("title", {"titles": ["一", "二", "三"]})), patch.object(
            supervisor_graph, "build_outline_graph", return_value=stage("outline", {"outline": "## 来源"}),
        ), patch.object(supervisor_graph, "build_content_graph", return_value=stage("content", {"content": "正文"})), patch.object(
            supervisor_graph, "make_quality_gate_node", return_value=review,
        ):
            result = supervisor_graph.build_supervisor_graph(max_review_rounds=1).invoke({
                "topic": "主题", "word_count": 100, "tool_traces": [{"tool": "previous"}],
            })
        self.assertEqual(seen, ["title", "outline", "outline", "content"])
        self.assertEqual((result["selected_title"], result["stage"]), ("一", "done"))
        self.assertTrue(result["review_result"]["passed"])


if __name__ == "__main__":
    unittest.main()
