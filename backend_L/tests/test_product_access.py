"""Product admission, authentication and media access with isolated accounts."""
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("LLM_API_KEY", "offline")
os.environ.setdefault("LLM_BASE_URL", "http://unused.invalid")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateSchema, DropSchema

from config.model_limits import limits
from config.settings import settings
from src.blog_agent.api.deps import get_db
from src.blog_agent.api.http_limits import install_http_limits, MAX_BODY_BYTES
from src.blog_agent.api.v1 import auth, articles, blog, media
from src.blog_agent.db.models import BlogTask, DownloadRecord, User, TaskStatus
from src.blog_agent.db.session import Base
from src.blog_agent.db.access_models import EmailChallenge
from src.blog_agent.service.auth_service import create_access_token, hash_password
from src.blog_agent.service.job_queue import active_jobs


class ProductAccessFixture(unittest.TestCase):
    def setUp(self):
        pg_url = os.getenv("POSTGRES_TEST_URL")
        if pg_url:
            namespace = "access_" + uuid4().hex
            admin = create_engine(pg_url)
            with admin.begin() as conn:
                conn.execute(CreateSchema(namespace))
            def clean():
                with admin.begin() as conn:
                    conn.execute(DropSchema(namespace, cascade=True))
                admin.dispose()
            self.addCleanup(clean)
            engine = create_engine(pg_url, connect_args={"options": f"-csearch_path={namespace}"})
        else:
            engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        self.sessions = sessionmaker(bind=engine)
        with self.sessions.begin() as db:
            for name in ("Author", "Reader"):
                db.add(User(username=name, nickname=name, email=name.lower()+"@example.com", password_hash="unused"))
        app = FastAPI()
        for router in (auth.router, articles.router, blog.router, media.router):
            app.include_router(router)
        install_http_limits(app)
        def override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = override
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.enterContext(patch.object(settings, "app_env", "test"))
        self.owner = {"Authorization": "Bearer " + create_access_token(1)}
        self.reader = {"Authorization": "Bearer " + create_access_token(2)}
        self.enterContext(patch.object(settings, "registration_mode", "auto"))
        self.enterContext(patch.object(limits, "enabled", True))

    def draft(self, user):
        result = self.client.post("/api/v1/task", json={"topic":"Scoped editorial test"}, headers=user)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["id"]


class ProductControls(ProductAccessFixture):
    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL statement snapshots")
    def test_quota_read_observes_one_commit_during_admission(self):
        from src.blog_agent.service.job_queue import enqueue

        task_id = self.draft(self.owner)
        admissions = []
        engine = self.sessions.kw["bind"]

        def admit_after_quota_select(conn, cursor, statement, params, context, executemany):
            if admissions or not statement.startswith("SELECT") or "FROM usage_window" not in statement:
                return
            admissions.append(task_id)
            with self.sessions.begin() as db:
                task = db.get(BlogTask, task_id, with_for_update=True)
                enqueue(db, task, "title")
                task.status = TaskStatus.RESEARCHING_TITLE

        event.listen(engine, "after_cursor_execute", admit_after_quota_select)
        try:
            response = self.client.get("/api/v1/auth/quota", headers=self.owner)
        finally:
            event.remove(engine, "after_cursor_execute", admit_after_quota_select)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(admissions, [task_id])
        before = response.json()
        self.assertEqual((before["used"], before["active_jobs"]), (0, 0))
        after = self.client.get("/api/v1/auth/quota", headers=self.owner).json()
        self.assertEqual((after["used"], after["active_jobs"]), (1, 1))

    def test_new_drafts_and_admitted_stages_have_separate_limits(self):
        self.enterContext(patch.object(settings, "free_daily_drafts", 2))
        self.enterContext(patch.object(settings, "free_daily_units", 1))
        self.enterContext(patch.object(settings, "free_max_active_jobs", 3))
        first, second = self.draft(self.owner), self.draft(self.owner)
        denied = self.client.post("/api/v1/task", json={"topic":"next"}, headers=self.owner)
        self.assertEqual(denied.status_code, 429)
        start = lambda i: self.client.post(f"/api/v1/task/{i}/generate-titles", headers=self.owner)
        self.assertEqual(start(first).status_code, 200)
        self.assertEqual(start(first).status_code, 409)
        limit = start(second)
        self.assertEqual(limit.status_code, 429)
        self.assertEqual(limit.json()["detail"]["code"], "daily_quota")
        self.assertGreater(int(limit.headers["Retry-After"]), 0)
        self.assertEqual(self.client.get(f"/api/v1/task/{second}", headers=self.owner).json()["status"], "pending")
        own = self.client.get("/api/v1/auth/quota", headers=self.owner).json()
        self.assertEqual((own["used"], own["remaining"], own["active_jobs"]), (1, 0, 1))
        self.assertEqual(self.client.get("/api/v1/auth/quota", headers=self.reader).json()["used"], 0)
        self.assertEqual(self.client.get("/api/v1/auth/quota").status_code, 401)

    def test_global_cap_and_pause_leave_no_charges(self):
        self.enterContext(patch.object(settings, "site_daily_units", 1))
        a, b = self.draft(self.owner), self.draft(self.reader)
        def start(i, who): return self.client.post(f"/api/v1/task/{i}/generate-titles", headers=who)
        with patch.object(limits, "enabled", False):
            self.assertEqual(start(a, self.owner).status_code, 503)
        self.assertEqual(start(a, self.owner).status_code, 200)
        self.assertEqual(start(b, self.reader).json()["detail"]["code"], "site_daily_limit")
        self.assertEqual(self.client.get("/api/v1/auth/quota", headers=self.reader).json()["used"], 0)

    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL contention")
    def test_parallel_different_tasks_cannot_overdraw(self):
        self.enterContext(patch.object(settings, "free_daily_units", 2))
        self.enterContext(patch.object(settings, "free_max_active_jobs", 8))
        tasks = [self.draft(self.owner) for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8) as executor:
            statuses = list(executor.map(lambda i: self.client.post(
                f"/api/v1/task/{i}/generate-titles", headers=self.owner).status_code, tasks))
        self.assertCountEqual(statuses, [200]*2 + [429]*6)
        with self.sessions() as db:
            self.assertEqual(active_jobs(db, 1), 2)

    def test_private_public_and_snapshot_media_permissions(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(patch.object(settings, "image_save_dir", directory))
        filename = "task1_12345678_1.png"
        url = "/images/" + filename
        Path(directory, filename).write_bytes(b"fixture")
        with self.sessions.begin() as db:
            db.add(BlogTask(id=1, user_id=1, topic="one", content=f"![Figure]({url})", status=TaskStatus.COMPLETED))
            db.add(BlogTask(id=2, user_id=2, topic="two", content=f"![Reference]({url})",
                            is_public=True, status=TaskStatus.COMPLETED))
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(url, headers=self.reader).status_code, 404)
        self.assertEqual(self.client.get(url, headers=self.owner).content, b"fixture")
        with self.sessions.begin() as db:
            task = db.get(BlogTask, 1)
            task.is_public = task.allow_download = True
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post("/api/v1/articles/1/download", headers=self.reader).status_code, 200)
        self.assertEqual(self.client.delete("/api/v1/task/1", headers=self.owner).status_code, 200)
        snap = self.client.get(url, headers=self.reader)
        self.assertEqual(snap.status_code, 200)
        self.assertIn("no-store", snap.headers["Cache-Control"])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_registration_mode_and_single_use_email_challenge(self):
        self.assertEqual(self.client.get("/api/v1/auth/config").json()["test_code"], settings.email_code_default)
        with patch.object(settings, "app_env", "production"), patch.object(settings, "smtp_host", None):
            self.assertEqual(self.client.get("/api/v1/auth/config").json()["registration_mode"], "closed")
            self.assertEqual(self.client.post("/api/v1/auth/send-code", json={"email":"new@example.com"}).status_code, 503)
            self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.owner).status_code, 401)
            production_owner = {"Authorization": "Bearer " + create_access_token(1)}
            self.assertEqual(self.client.post("/api/v1/auth/recharge", headers=production_owner,
                json={"amount":1, "verify_code":settings.email_code_default}).status_code, 403)
        with patch.object(settings, "registration_mode", "smtp"), patch(
                "src.blog_agent.service.email_verification._send_mail") as mail:
            self.assertIsNone(self.client.get("/api/v1/auth/config").json()["test_code"])
            email = "new@example.com"
            issue = self.client.post("/api/v1/auth/send-code", json={"email":email})
            self.assertEqual(issue.status_code, 200)
            self.assertNotIn("code", issue.json())
            _, code = mail.call_args.args
            data = dict(nickname="Author3",username="NewAuthor",email=email,password="Letters123",confirm_password="Letters123",email_code=code)
            self.assertEqual(self.client.post("/api/v1/auth/register", json=data).status_code, 200)
            self.assertEqual(self.client.post("/api/v1/auth/register", json={**data,"username":"Another"}).status_code, 400)
            with self.sessions() as db: self.assertIsNone(db.get(EmailChallenge, email))

    def test_auth_throttle_and_password_revocation(self):
        with patch.object(settings, "auth_login_per_ip", 1):
            data = {"account":"unused","password":"irrelevant"}
            self.assertEqual(self.client.post("/api/v1/auth/login", json=data).status_code, 401)
            self.assertEqual(self.client.post("/api/v1/auth/login", json=data).status_code, 429)
        with self.sessions.begin() as db:
            db.get(User,1).password_hash = hash_password("Previous01")
        update = {"old_password":"Previous01","new_password":"Updated123","confirm_new_password":"Updated123"}
        self.assertEqual(self.client.put("/api/v1/auth/password", headers=self.owner, json=update).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.owner).status_code, 401)
        fresh = self.client.post("/api/v1/auth/login", json={"account":"Author","password":"Updated123"}).json()["access_token"]
        self.assertEqual(self.client.get("/api/v1/auth/me",headers={"Authorization":"Bearer "+fresh}).status_code, 200)

    def test_api_body_ceiling_applies_before_validation(self):
        result = self.client.post("/api/v1/auth/login", content=b" "*(MAX_BODY_BYTES+1), headers={"Content-Type":"application/json"})
        self.assertEqual(result.status_code, 413)
        self.assertIn("no-store", result.headers["cache-control"])


@unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires independent PostgreSQL sessions")
class ConcurrentAccountIsolation(ProductAccessFixture):
    """Ordinary signed-in clients operating on known synthetic manuscripts."""

    def accounts(self, count):
        with self.sessions.begin() as db:
            for index in range(3, count + 1):
                db.add(User(username=f"Editor{index}", nickname=f"Editor{index}",
                            email=f"editor{index}@example.org", password_hash="unused"))
            db.flush()
            ids = [uid for (uid,) in db.query(User.id).order_by(User.id)]
        return [(uid, {"Authorization": "Bearer " + create_access_token(uid)}) for uid in ids]

    def parallel(self, cases, operation):
        gate = Barrier(len(cases), timeout=15)
        def run(case):
            with TestClient(self.client.app) as client:
                gate.wait()
                operation(client, case)
        with ThreadPoolExecutor(max_workers=len(cases)) as pool:
            list(pool.map(run, cases))

    def check(self, client, method, path, headers=None, expected=200, **options):
        response = client.request(method, path, headers=headers or {}, **options)
        self.assertEqual(response.status_code, expected, (method, path, response.text[:200]))
        return response

    def test_parallel_draft_lists_progress_and_edits(self):
        accounts = self.accounts(8)
        tasks = [self.draft(headers) for _, headers in accounts]
        with self.sessions.begin() as db:
            for (uid, _), task_id in zip(accounts, tasks):
                task = db.get(BlogTask, task_id)
                task.status = TaskStatus.OUTLINE_GENERATED
                task.outline = f"Draft {uid}"
                task.progress = f"Outline ready for editor {uid}"
        # The SSE generator intentionally creates a fresh session for each update.
        self.enterContext(patch("src.blog_agent.db.session.SessionLocal", self.sessions))

        def exercise(client, index):
            uid, headers = accounts[index]
            task_id, peer_id = tasks[index], tasks[(index + 1) % len(tasks)]
            for collection, field in [("/api/v1/task", "id"), ("/api/v1/my/articles?tab=created", "task_id")]:
                body = self.check(client, "GET", collection, headers).json()
                self.assertEqual((body["total"], [row[field] for row in body["items"]]), (1, [task_id]))
            own, peer = f"/api/v1/task/{task_id}", f"/api/v1/task/{peer_id}"
            task = self.check(client, "GET", own, headers).json()
            self.assertEqual((task["user_id"], task["outline"]), (uid, f"Draft {uid}"))
            stream = self.check(client, "GET", own + "/stream", headers)
            event = next(line for line in stream.text.splitlines() if line.startswith("data: "))
            self.assertEqual(json.loads(event[6:])["progress"], f"Outline ready for editor {uid}")
            for path in (peer, peer + "/stream"):
                self.check(client, "GET", path, headers, expected=403)
            edits = {"outline": f"Approved by editor {uid}", "word_count": 600 + uid}
            self.check(client, "POST", peer + "/confirm-outline", headers, expected=403, json=edits)
            saved = self.check(client, "POST", own + "/confirm-outline", headers, json=edits).json()
            self.assertEqual((saved["id"], saved["outline"], saved["word_count"]),
                             (task_id, edits["outline"], edits["word_count"]))

        self.parallel(range(len(tasks)), exercise)
        for (uid, headers), task_id in zip(accounts, tasks):
            current = self.check(self.client, "GET", f"/api/v1/task/{task_id}", headers).json()
            self.assertEqual(current["outline"], f"Approved by editor {uid}")

    def test_parallel_receipts_and_quota_are_independent(self):
        self.enterContext(patch.object(settings, "free_daily_units", 2))
        self.enterContext(patch.object(settings, "free_max_active_jobs", 4))
        self.enterContext(patch.object(settings, "site_daily_units", 20))
        first, second = self.draft(self.owner), self.draft(self.reader)
        with self.sessions.begin() as db:
            db.get(BlogTask, second).status = TaskStatus.TITLE_GENERATED
        title = {"title": "Reader's custom headline", "need_image": False}
        same_key = {"Idempotency-Key": "fixture-stage-click"}
        cases = [
            (first, "generate-titles", {**self.owner, **same_key}, None, "title"),
            (second, "submit-title-config", {**self.reader, **same_key}, title, "outline"),
        ]
        def submit(client, case):
            task_id, action, headers, payload, stage = case
            body = self.check(client, "POST", f"/api/v1/task/{task_id}/{action}", headers, json=payload).json()
            self.assertEqual((body["id"], body["job"]["stage"], body["job"]["status"]), (task_id, stage, "queued"))
        self.parallel(cases * 2, submit)
        # A successful replay still authenticates the owner before returning the receipt.
        self.check(self.client, "POST", f"/api/v1/task/{first}/generate-titles",
                   {**self.reader, **same_key}, expected=403)
        for headers in (self.owner, self.reader):
            q = self.check(self.client, "GET", "/api/v1/auth/quota", headers).json()
            self.assertEqual((q["used"], q["remaining"], q["active_jobs"]), (1, 1, 1))
        extra, over = self.draft(self.owner), self.draft(self.owner)
        self.check(self.client, "POST", f"/api/v1/task/{extra}/generate-titles", self.owner)
        denied = self.check(self.client, "POST", f"/api/v1/task/{over}/generate-titles", self.owner, expected=429)
        self.assertEqual(denied.json()["detail"]["code"], "daily_quota")
        for headers, used in [(self.owner, 2), (self.reader, 1)]:
            q = self.check(self.client, "GET", "/api/v1/auth/quota", headers).json()
            self.assertEqual((q["used"], q["remaining"], q["active_jobs"]), (used, 2 - used, used))
        self.check(self.client, "GET", "/api/v1/auth/quota", expected=401)

    def test_saved_editions_after_visibility_change(self):
        (_, author), (buyer_id, buyer), (_, downloader), (_, observer) = self.accounts(4)
        task_id = self.draft(author)
        current = f"/api/v1/articles/{task_id}"
        visibility = f"/api/v1/task/{task_id}/visibility"
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.object(settings, "image_save_dir", str(directory)))
        old_name, new_name = (f"task{task_id}_{version}_1.png" for version in ("first", "second"))
        old_url, new_url = "/images/" + old_name, "/images/" + new_name
        for name in [old_name, new_name]:
            (directory / name).write_bytes(name.encode())
        old_body = f"Published edition\n![Figure]({old_url})"
        new_body = f"New private edition\n![Figure]({new_url})"
        with self.sessions.begin() as db:
            task = db.get(BlogTask, task_id)
            task.status, task.formatted_content = TaskStatus.COMPLETED, old_body
            task.review_feedback = '{"passed":true,"policy_version":1}'
            db.get(User, buyer_id).balance = 10

        def publish(public, price):
            edition = self.check(self.client, "GET", f"/api/v1/task/{task_id}", author).json()["revision"]
            self.check(self.client, "PUT", visibility, author, json={
                "is_public": public, "allow_download": public, "download_price": price,
                "expected_revision": edition,
            })
        publish(True, 0)
        self.assertEqual(self.check(self.client, "GET", current).json()["content"], old_body)
        self.check(self.client, "GET", old_url)
        self.check(self.client, "POST", current + "/download", downloader)
        publish(True, 3)
        quote = self.check(self.client, "GET", current).json()
        self.check(self.client, "POST", current + "/purchase", buyer, json={
            "expected_revision": quote["revision"], "expected_price": quote["download_price"],
        })
        publish(False, 0)
        with self.sessions.begin() as db:
            db.get(BlogTask, task_id).formatted_content = new_body

        snapshots = []
        for kind, user in [("downloaded", downloader), ("purchased", buyer)]:
            collection = f"/api/v1/my/articles?tab={kind}"
            edition = self.check(self.client, "GET", collection, user).json()["items"][0]
            self.assertFalse(edition["topic"])  # a private manuscript's current metadata is not listed
            snapshots.append((f"/api/v1/my/articles/{kind}/{edition['record_id']}", user))
            self.assertEqual(self.check(self.client, "GET", collection, observer).json()["total"], 0)

        def read_edition(client, case):
            headers, owns_current, has_saved = case
            resp = self.check(client, "GET", current, headers, expected=200 if owns_current else 404)
            if owns_current:
                self.assertEqual(resp.json()["content"], new_body)
            self.check(client, "GET", new_url, headers, expected=200 if owns_current else 404)
            if not owns_current:
                resp = self.check(client, "GET", old_url, headers, expected=200 if has_saved else 404)
                if has_saved:
                    self.assertEqual(resp.content, old_name.encode())
            for path, holder in snapshots:
                own_snapshot = holder == headers
                expected = 401 if headers is None else (200 if own_snapshot else 404)
                resp = self.check(client, "GET", path, headers, expected=expected)
                if own_snapshot:
                    self.assertEqual(resp.json()["content"], old_body)

        self.parallel([(author, True, False), (buyer, False, True), (downloader, False, True),
                       (observer, False, False), (None, False, False)], read_edition)
        self.check(self.client, "DELETE", f"/api/v1/task/{task_id}", author)
        for path, holder in snapshots:
            self.assertEqual(self.check(self.client, "GET", path, holder).json()["content"], old_body)
            self.check(self.client, "GET", old_url, holder)
        self.check(self.client, "GET", old_url, observer, expected=404)
