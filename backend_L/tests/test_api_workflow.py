"""HTTP workflow regressions. Set POSTGRES_TEST_URL to also exercise row locking."""
import os
import hashlib
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateSchema, DropSchema

os.environ.setdefault("LLM_API_KEY", "test")
os.environ.setdefault("LLM_BASE_URL", "http://unused.invalid")

from src.blog_agent.api.deps import get_db
from src.blog_agent.api.v1 import articles, blog, revisions
from src.blog_agent.db.job_models import GenerationJob, GenerationRequest
from src.blog_agent.service import job_queue
from src.blog_agent.service.job_worker import execute_claim
from src.blog_agent.service.quota_service import quota_for
from src.blog_agent.db.models import BlogTask, TaskStatus, User
from src.blog_agent.db.session import Base, upgrade_editorial_schema
from src.blog_agent.service.auth_service import create_access_token


class EditorialMigration(unittest.TestCase):
    def test_upgrade_is_repeatable_and_preserves_earlier_jobs_and_text(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        with engine.begin() as db:
            db.execute(text("CREATE TABLE blog_task (id INTEGER PRIMARY KEY, content TEXT)"))
            db.execute(text("INSERT INTO blog_task (id, content) VALUES (1,'existing draft')"))
            db.execute(text("CREATE TABLE generation_jobs (id INTEGER PRIMARY KEY, stage TEXT)"))
            db.execute(text("INSERT INTO generation_jobs (id, stage) VALUES (1,'content')"))
            upgrade_editorial_schema(db)
            upgrade_editorial_schema(db)
            self.assertEqual(db.execute(text("SELECT content, editorial_version, evidence_sources FROM blog_task")).one(),
                             ("existing draft", 0, None))
            self.assertEqual(db.execute(text("SELECT stage, review_only FROM generation_jobs")).one(), ("content", 0))
            self.assertIn("purpose", {col["name"] for col in inspect(db).get_columns("blog_task")})


class DatabaseCase(unittest.TestCase):
    def setUp(self):
        pg_url = os.getenv("POSTGRES_TEST_URL")
        if pg_url:
            schema = "workflow_test_" + uuid4().hex
            admin = create_engine(pg_url)
            with admin.begin() as connection:
                connection.execute(CreateSchema(schema))

            def remove_schema():
                with admin.begin() as connection:
                    connection.execute(DropSchema(schema, cascade=True))
                admin.dispose()

            self.addCleanup(remove_schema)
            engine = create_engine(pg_url, connect_args={"options": f"-csearch_path={schema}"})
        else:
            engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)
        with self.session.begin() as db:
            for name in ("author", "reader"):
                db.add(User(username=name, nickname=name, email=f"{name}@example.com", password_hash="test", balance=20))
        self.author = {"Authorization": "Bearer " + create_access_token(1)}
        self.reader = {"Authorization": "Bearer " + create_access_token(2)}
        self.app = FastAPI()
        self.app.include_router(blog.router)
        self.app.include_router(articles.router)
        self.app.include_router(revisions.router)

        def session_override():
            with self.session() as db:
                yield db

        self.app.dependency_overrides[get_db] = session_override
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def make_task(self, status=TaskStatus.PENDING, **fields):
        with self.session.begin() as db:
            task = BlogTask(user_id=1, topic="Test topic", status=status, **fields)
            db.add(task)
            db.flush()
            return task.id


class WorkflowAPI(DatabaseCase):
    def test_title_receipts_remain_replayable_after_the_brief_upgrade(self):
        task_id = self.make_task(TaskStatus.OUTLINE_GENERATED)
        url = f"/api/v1/task/{task_id}/submit-title-config"
        key = "from-the-previous-release"
        payload = {"title": "Title", "need_image": False, "article_style": None,
                   "article_style_custom": None, "extra_requirements": None}
        command = json.dumps(["submit-title-config", payload], sort_keys=True, separators=(",", ":"))
        with self.session.begin() as db:
            db.add(GenerationRequest(task_id=task_id, key_hash=hashlib.sha256(key.encode()).hexdigest(),
                                     command_hash=hashlib.sha256(command.encode()).hexdigest()))
        headers = {**self.author, "Idempotency-Key": key}
        self.assertEqual(self.client.post(url, json={"title": "Title"}, headers=headers).status_code, 200)
        self.assertEqual(self.client.post(url, json={"title": "Title", "purpose": "不同简报"}, headers=headers).status_code, 409)
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 0)

    def test_private_review_is_versioned_isolated_and_charged_once(self):
        old_body, new_body = "# Original\nOld edition", "# Original\nCorrected private edition"
        task_id = self.make_task(TaskStatus.COMPLETED, selected_title="Original", formatted_content=old_body,
                                 is_public=True, allow_download=True, download_price=5)
        task = f"/api/v1/task/{task_id}"
        article = f"/api/v1/articles/{task_id}"
        url = task + "/revision"
        original = self.client.get(article).json()["revision"]
        save = {"content": new_body, "expected_version": 0, "expected_revision": original}
        self.assertEqual(self.client.put(url, json=save, headers=self.reader).status_code, 403)
        self.assertEqual(self.client.get(url, headers=self.reader).status_code, 403)
        draft = self.client.put(url, json=save, headers=self.author).json()
        version = {"expected_version": draft["version"]}
        apply = dict(version, expected_revision=original)
        self.assertEqual(self.client.post(url + "/apply", json=apply, headers=self.author).status_code, 409)
        headers = {**self.author, "Idempotency-Key": "editor-submit"}
        for _ in range(2):
            submitted = self.client.post(url + "/review", json=version, headers=headers)
            self.assertEqual(submitted.json()["status"], "queued")
        self.assertEqual(self.client.get(article).json()["content"], old_body)
        with self.session.begin() as db:
            self.assertEqual(quota_for(db, 1)["used"], 1)
            self.assertEqual(quota_for(db, 2)["used"], 0)
            claim = job_queue.claim_next(db)
        approved = {"passed": True, "score": 95, "policy_version": 1}
        with patch("src.blog_agent.service.agent_service._CONTENT_GATE", return_value={"review_result": approved}) as gate:
            execute_claim(claim, sessions=self.session)
        state = gate.call_args.args[0]
        self.assertTrue(state["force_review"] and state["editor_revision"])
        self.assertEqual(state["content"], new_body)
        self.assertEqual(state["word_count"], 100)
        self.assertEqual(self.client.get(article).json()["content"], old_body)
        self.assertEqual(self.client.get(url, headers=self.author).json()["status"], "approved")
        adopted = self.client.post(url + "/apply", json=apply, headers=self.author).json()
        self.assertFalse(adopted["is_public"])
        self.assertNotEqual(adopted["revision"], original)
        self.assertEqual(self.client.get(article).status_code, 404)
        self.assertEqual(self.client.post(url + "/apply", json=apply, headers=self.author).status_code, 200)
        publication = {"is_public": True, "allow_download": True, "download_price": 7, "expected_revision": original}
        self.assertEqual(self.client.put(task + "/visibility", json=publication, headers=self.author).status_code, 409)
        publication["expected_revision"] = adopted["revision"]
        self.assertEqual(self.client.put(task + "/visibility", json=publication, headers=self.author).status_code, 200)
        self.assertEqual(self.client.get(article).json()["content"], new_body)
        for seen, price in [(original, 7), (adopted["revision"], 5)]:
            quote = {"expected_revision": seen, "expected_price": price}
            self.assertEqual(self.client.post(article + "/purchase", json=quote, headers=self.reader).status_code, 409)
        with self.session() as db:
            self.assertEqual(db.get(User, 2).balance, 20)
            self.assertEqual(quota_for(db, 1)["used"], 1)
            self.assertEqual(quota_for(db, 1)["active_jobs"], 0)

    def test_failed_revision_preserves_publication_and_replay_does_not_rebill(self):
        task_id = self.make_task(TaskStatus.COMPLETED, content="# Original", is_public=True)
        root = f"/api/v1/task/{task_id}"
        base = self.client.get(root, headers=self.author).json()["revision"]
        url = root + "/revision"
        first = self.client.put(url, json={"expected_revision": base, "expected_version": 0, "content": "# Edited"},
                                headers=self.author).json()
        version = {"expected_version": first["version"]}
        headers = {**self.author, "Idempotency-Key": "first-review"}
        self.assertEqual(self.client.post(url + "/review", json=version, headers=headers).status_code, 200)
        with self.session.begin() as db:
            claim = job_queue.claim_next(db)
        with self.session.begin() as db:
            self.assertEqual(job_queue.begin_execution(db, claim)[0], "revision")
        with self.session.begin() as db:
            job_queue.abandon(db, claim)
        replay = self.client.post(url + "/review", json=version, headers=headers)
        self.assertEqual(replay.json()["status"], "failed")
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 1)
        self.assertEqual(self.client.get(f"/api/v1/articles/{task_id}").json()["content"], "# Original")
        self.assertEqual(self.client.delete(url, params=version, headers=self.author).status_code, 200)
        second = self.client.put(url, json={"expected_revision": base, "expected_version": 0, "content": "# New"},
                                 headers=self.author).json()
        self.assertGreater(second["version"], first["version"])
        self.assertEqual(self.client.delete(url, params=version, headers=self.author).status_code, 409)

    def test_brief_survives_stage_submission_and_legacy_publication_needs_review(self):
        brief = {"topic": "主题", "purpose": "帮助读者完成初次配置", "level": "general",
                 "word_count": 300, "article_style": "note"}
        created = self.client.post("/api/v1/task", json=brief, headers=self.author).json()
        task = f"/api/v1/task/{created['id']}"
        queued = self.client.post(task + "/generate-titles", headers=self.author).json()
        self.assertEqual({k: queued[k] for k in brief}, brief)
        with self.session.begin() as db:
            row = db.get(BlogTask, created["id"])
            row.status, row.formatted_content = TaskStatus.COMPLETED, "# Legacy"
            row.review_feedback = '{"passed":true,"skipped":true}'
        base = self.client.get(task, headers=self.author).json()["revision"]
        rejected = self.client.put(task + "/visibility", json={"is_public": True, "expected_revision": base}, headers=self.author)
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()["detail"]["code"], "review_required")

    def test_factual_edit_can_supplement_old_sources_without_rewriting_or_republishing(self):
        task_id = self.make_task(TaskStatus.COMPLETED, selected_title="开馆", content="# 开馆\n参观须预约。",
                                 article_style="technical", is_public=True)
        root = f"/api/v1/task/{task_id}"
        url = root + "/revision"
        base = self.client.get(root, headers=self.author).json()["revision"]
        result = self.client.put(url, json={"expected_revision": base, "expected_version": 0,
                                "content": "# 开馆\n参观须预约。", "source_query": "本馆预约公告"}, headers=self.author)
        version = {"expected_version": result.json()["version"]}
        self.assertEqual(self.client.post(url + "/review", json=version, headers=self.author).status_code, 422)
        record = {"title": "预约须知", "url": "https://museum.example/open", "excerpt": "入馆请提前预约。"}
        headers = {**self.author, "Idempotency-Key": "supplement"}
        self.client.post(url + "/review", json=version, headers=headers).raise_for_status()
        with self.session.begin() as db:
            claim = job_queue.claim_next(db)
        with patch("src.blog_agent.service.editorial.web_search") as search:
            search.invoke.return_value = {"status": "ok", "sources": [record]}
            execute_claim(claim, sessions=self.session)
        draft = self.client.get(url, headers=self.author).json()
        self.assertEqual(draft["status"], "rejected")
        self.assertEqual(draft["evidence_sources"][0]["url"], record["url"])
        self.assertIn("引用", str(draft["review_result"]))
        self.assertEqual(draft["content"], "# 开馆\n参观须预约。")
        original = self.client.get(root, headers=self.author).json()
        self.assertTrue(original["is_public"])
        self.assertEqual(original["evidence_sources"], [])
        self.assertEqual(original["revision"], base)

    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL row locks")
    def test_competing_edit_review_admissions_charge_one_job(self):
        task_id = self.make_task(TaskStatus.COMPLETED, content="# Example")
        root = f"/api/v1/task/{task_id}"
        url = root + "/revision"
        base = self.client.get(root, headers=self.author).json()["revision"]
        draft = self.client.put(url, json={"content": "# New", "expected_revision": base, "expected_version": 0},
                                headers=self.author).json()
        start = Barrier(4)
        def submit(index):
            start.wait()
            return self.client.post(url + "/review", headers={**self.author, "Idempotency-Key": f"click-{index % 2}"},
                                    json={"expected_version": draft["version"]}).status_code
        with ThreadPoolExecutor(4) as pool:
            self.assertEqual(list(pool.map(submit, range(4))), [200] * 4)
        with self.session() as db:
            self.assertEqual(db.query(GenerationJob).filter_by(task_id=task_id).count(), 1)
            self.assertEqual(quota_for(db, 1)["used"], 1)

    def test_title_restart_invalidates_old_edition_and_rejects_duplicate(self):
        task_id = self.make_task(
            TaskStatus.COMPLETED, outline="Old outline", outline_confirmed=True, content="Old draft",
            selected_title="Old title", is_public=True, allow_download=True, download_price=2,
            formatted_content="Old edition", image_urls='["old.png"]', review_feedback="Old review",
        )
        url = f"/api/v1/task/{task_id}"
        response = self.client.post(url + "/generate-titles", headers=self.author)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["status"], "researching_title")
        for field in ("outline", "outline_confirmed", "selected_title", "content", "formatted_content",
                      "image_urls", "is_public", "allow_download", "download_price", "review_feedback"):
            self.assertFalse(result[field], field)
        self.assertEqual(self.client.post(url + "/generate-titles", headers=self.author).status_code, 409)
        self.assertEqual(self.client.post(url + "/generate-content", headers=self.author).status_code, 409)
        self.assertEqual(result["job"]["status"], "queued")

    def test_title_configuration_survives_queue_failure_and_outline_retry(self):
        task_id = self.make_task(TaskStatus.TITLE_GENERATED)
        url = f"/api/v1/task/{task_id}"
        response = self.client.post(url + "/submit-title-config", json={"title": "Edited title"}, headers=self.author)
        self.assertEqual(response.json()["job"]["status"], "queued")
        with self.session.begin() as db:
            claim = job_queue.claim_next(db)
        with self.session.begin() as db:
            job_queue.begin_execution(db, claim)
        with self.session.begin() as db:
            job_queue.abandon(db, claim)
        saved = self.client.get(url, headers=self.author).json()
        self.assertEqual((saved["status"], saved["selected_title"]), ("failed", "Edited title"))
        summary = self.client.get("/api/v1/my/articles", headers=self.author).json()["items"][0]
        self.assertEqual((summary["selected_title"], summary["outline_confirmed"]), ("Edited title", False))
        response = self.client.post(url + "/regenerate-outline", headers=self.author)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["error"])
        self.assertEqual(response.json()["status"], "researching_outline")
        self.assertEqual(response.json()["job"]["stage"], "outline")

    def test_content_retry_requires_approved_outline_and_preserves_configuration(self):
        task_id = self.make_task(TaskStatus.OUTLINE_GENERATED, selected_title="Title", outline="Outline")
        url = f"/api/v1/task/{task_id}"
        self.assertEqual(self.client.post(url + "/generate-content", headers=self.author).status_code, 400)
        self.assertEqual(self.client.post(url + "/confirm-outline", json={"outline": " "}, headers=self.author).status_code, 400)
        self.assertEqual(self.client.post(url + "/confirm-outline", json={"word_count": 500}, headers=self.author).status_code, 200)
        with self.session.begin() as db:
            row = db.get(BlogTask, task_id)
            row.status, row.error = TaskStatus.FAILED, "previous failure"
        response = self.client.post(url + "/generate-content", headers=self.author)
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        self.assertEqual((task["status"], task["word_count"], task["outline"]), ("researching_content", 500, "Outline"))
        self.assertIsNone(task["error"])
        self.assertEqual(task["job"]["stage"], "content")

    def test_stream_finishes_at_human_checkpoint(self):
        task_id = self.make_task(TaskStatus.TITLE_GENERATED)
        with patch("src.blog_agent.db.session.SessionLocal", self.session):
            response = self.client.get(f"/api/v1/task/{task_id}/stream", headers=self.author)
        self.assertEqual(response.status_code, 200)
        self.assertIn('"status": "title_generated"', response.text)
        self.assertIn("event: done", response.text)

    def test_reopen_failed_draft_preserves_review_until_new_submission(self):
        task_id = self.make_task(TaskStatus.FAILED, outline="A", outline_confirmed=True,
                                 content="Earlier draft", review_feedback='{"score": 70}',
                                 level="advanced", word_count=500, error="review failed")
        url = f"/api/v1/task/{task_id}"
        reopen = url + "/reopen-outline"
        self.assertEqual(self.client.post(reopen, headers=self.reader).status_code, 403)
        with self.session.begin() as db:
            db.get(BlogTask, task_id).is_public = True
        self.assertEqual(self.client.post(reopen, headers=self.author).status_code, 409)
        with self.session.begin() as db:
            db.get(BlogTask, task_id).is_public = False
        response = self.client.post(reopen, headers=self.author)
        self.assertEqual(response.status_code, 200, response.text)
        task = response.json()
        self.assertEqual((task["status"], task["outline_confirmed"], task["error"]), ("outline_generated", False, None))
        self.assertEqual((task["outline"], task["level"], task["word_count"]), ("A", "advanced", 500))
        self.assertEqual((task["content"], task["review_result"]), ("Earlier draft", {"score": 70}))
        self.assertEqual(self.client.post(reopen, headers=self.author).status_code, 409)
        self.assertEqual(self.client.post(url + "/confirm-outline", json={"outline": "B"}, headers=self.author).status_code, 200)
        updated = self.client.post(url + "/generate-content", headers=self.author).json()
        self.assertEqual(updated["outline"], "B")
        self.assertEqual((updated["word_count"], updated["level"]), (500, "advanced"))
        self.assertIsNone(updated["content"])
        self.assertIsNone(updated["review_result"])
        self.assertEqual(self.client.post(reopen, headers=self.author).status_code, 409)

    def test_task_review_and_completion_note_match_the_saved_draft(self):
        note = "文章已完成，成功配图 0/1 张"
        task_id = self.make_task(TaskStatus.COMPLETED, progress=note, review_feedback='{"score": 92}')
        task = self.client.get(f"/api/v1/task/{task_id}", headers=self.author).json()
        detail = self.client.get(f"/api/v1/blog/{task_id}", headers=self.author).json()
        self.assertEqual(task["review_result"], {"score": 92})
        self.assertEqual(detail["progress"], note)
        with self.session.begin() as db:
            db.get(BlogTask, task_id).review_feedback = "早期版本的审稿意见"
        task = self.client.get(f"/api/v1/task/{task_id}", headers=self.author).json()
        self.assertEqual(task["review_result"], {"opinions_text": "早期版本的审稿意见"})

    def test_private_download_and_reader_snapshots_after_deletion(self):
        task_id = self.make_task(TaskStatus.COMPLETED, formatted_content="# Original", download_price=5)
        article = f"/api/v1/articles/{task_id}"
        self.assertEqual(self.client.post(article + "/download", headers=self.author).json()["content"], "# Original")
        self.assertEqual(self.client.post(article + "/download", headers=self.reader).status_code, 404)
        with self.session.begin() as db:
            db.get(BlogTask, task_id).is_public = True
        quote = {"expected_revision": self.client.get(article).json()["revision"], "expected_price": 5}
        self.assertEqual(self.client.post(article + "/purchase", headers=self.reader, json=quote).status_code, 403)
        with self.session.begin() as db:
            db.get(BlogTask, task_id).allow_download = True
        for _ in range(2):
            res = self.client.post(article + "/purchase", headers=self.reader, json=quote)
            self.assertEqual(res.status_code, 200, res.text)
            self.assertEqual(res.json()["balance"], 15)
        for action in ("like", "favorite", "download"):
            self.assertEqual(self.client.post(article + "/" + action, headers=self.reader).status_code, 200)
        for tab in ("liked", "favorited"):
            res = self.client.get("/api/v1/my/articles", params={"tab": tab}, headers=self.reader)
            self.assertEqual(res.json()["items"][0]["task_id"], task_id)
        cards = self.client.get("/api/v1/articles/search", params={"q": "Test"}, headers=self.reader).json()
        self.assertTrue(cards["items"][0]["liked"])
        self.assertEqual(cards["items"][0]["favorite_count"], 1)
        self.assertEqual(self.client.delete(f"/api/v1/task/{task_id}", headers=self.author).status_code, 200)
        for tab in ("purchased", "downloaded"):
            res = self.client.get("/api/v1/my/articles", params={"tab": tab}, headers=self.reader)
            record = res.json()["items"][0]
            self.assertEqual(record["task_id"], 0)
            snapshot = f"/api/v1/my/articles/{tab}/{record['record_id']}"
            self.assertEqual(self.client.get(snapshot, headers=self.reader).json()["content"], "# Original")
            self.assertEqual(self.client.get(snapshot, headers=self.author).status_code, 404)
        with self.session() as db:
            self.assertEqual(db.get(User, 1).balance, 25)

    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL row locks")
    def test_overlapping_submissions_have_a_single_worker(self):
        task_id = self.make_task()
        url = f"/api/v1/task/{task_id}/generate-titles"
        barrier = Barrier(4)

        def submit_once(_):
            barrier.wait(timeout=10)
            return self.client.post(url, headers=self.author).status_code

        with ThreadPoolExecutor(4) as workers:
            results = sorted(workers.map(submit_once, range(4)))
            self.assertEqual(results, [200, 409, 409, 409])
        with self.session() as db:
            self.assertEqual(db.query(GenerationJob).count(), 1)
