"""Stage claims, bounded restart recovery and stale writer protection."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import Mock, patch

from sqlalchemy import event
from sqlalchemy.exc import OperationalError

import test_api_workflow as fixtures
from config.settings import settings
from src.blog_agent.api.v1.blog import _stream_slot
from src.blog_agent.db.access_models import WindowCounter
from src.blog_agent.db.job_models import GenerationJob, GenerationReservation
from src.blog_agent.db.models import BlogTask, TaskStatus
from src.blog_agent.service import job_queue
from src.blog_agent.service.job_worker import execute_claim
from src.blog_agent.service.quota_service import DAY, quota_for
from src.blog_agent.service.task_service import TaskService


class DurableJobs(fixtures.DatabaseCase):
    def submit_title(self, task_id):
        return self.client.post(f"/api/v1/task/{task_id}/generate-titles", headers=self.author)

    def claim(self):
        with self.session.begin() as db:
            return job_queue.claim_next(db)

    def expire(self, claim):
        with self.session.begin() as db:
            db.get(GenerationJob, claim.job_id).lease_until = datetime(2000, 1, 1, tzinfo=timezone.utc)

    def test_accepted_request_is_durable_and_finishes_with_its_artifact(self):
        task_id = self.make_task()
        self.assertEqual(self.submit_title(task_id).status_code, 200)
        claim = self.claim()

        def titles(task_id, topic):
            with self.session() as db:
                TaskService.save_titles(db, task_id, [topic + " A"])

        execute_claim(claim, self.session, {"title": titles})
        with self.session() as db:
            self.assertEqual(job_queue.active_jobs(db, 1), 0)
            self.assertEqual(job_queue.latest_job(db, task_id)["status"], "succeeded")
            self.assertEqual(db.get(BlogTask, task_id).status, TaskStatus.TITLE_GENERATED)
        self.assertIsNone(self.claim())

    def test_delayed_http_replay_returns_current_artifact_without_billing_again(self):
        task_id = self.make_task()
        url = f"/api/v1/task/{task_id}"
        headers = dict(self.author, **{"Idempotency-Key": "first-click"})
        response = self.client.post(url + "/generate-titles", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)

        def generate(task_id, topic):
            with self.session() as db:
                TaskService.save_titles(db, task_id, [topic + " A"])

        execute_claim(self.claim(), self.session, {"title": generate})
        replay = self.client.post(url + "/generate-titles", headers=headers)
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual((replay.json()["status"], replay.json()["job"]["status"]), ("title_generated", "succeeded"))
        with self.session() as db:
            self.assertEqual(db.query(GenerationJob).count(), 1)
            self.assertEqual(quota_for(db, 1)["used"], 1)
        response = self.client.post(url + "/submit-title-config", headers=headers, json={"title": "A"})
        self.assertEqual(response.status_code, 409)
        headers["Idempotency-Key"] = "second-click"
        self.assertEqual(self.client.post(url + "/submit-title-config", headers=headers, json={"title": "A"}).status_code, 200)
        conflict = self.client.post(url + "/submit-title-config", headers=headers, json={"title": "Changed"})
        self.assertEqual(conflict.json()["detail"]["code"], "idempotency_conflict")
        replay = self.client.post(url + "/submit-title-config", headers=headers, json={"title": "A"})
        self.assertEqual(replay.status_code, 200)
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 2)

    def test_claims_lost_before_provider_use_retry_a_bounded_number_of_times(self):
        task_id = self.make_task()
        url = f"/api/v1/task/{task_id}/generate-titles"
        original_headers = {**self.author, "Idempotency-Key": "original"}
        with patch.object(settings, "agent_job_max_attempts", 2):
            self.assertEqual(self.client.post(url, headers=original_headers).status_code, 200)
        first = self.claim()
        self.expire(first)
        second = self.claim()
        self.assertEqual(first.job_id, second.job_id)
        self.assertNotEqual(first.token, second.token)
        with self.assertRaises(job_queue.LeaseLost), self.session.begin() as db:
            job_queue.begin_execution(db, first)
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 1)
            self.assertEqual(db.get(GenerationReservation, first.job_id).units, 1)
        self.expire(second)
        self.assertIsNone(self.claim())
        self.assertIsNone(self.claim())
        with self.assertRaises(job_queue.LeaseLost), self.session.begin() as db:
            job_queue.abandon(db, second)
        replay = self.client.post(url, headers=original_headers).json()
        self.assertEqual(replay["job"]["status"], "failed")
        self.assertIn("已退回", replay["error"])
        with self.session() as db:
            job = db.get(GenerationJob, first.job_id)
            self.assertEqual((job.status, job.attempt), ("failed", 2))
            self.assertEqual(db.get(BlogTask, task_id).status, TaskStatus.FAILED)
            self.assertIsNone(db.get(GenerationReservation, job.id))
            self.assertEqual(quota_for(db, 1)["used"], 0)
        retry_headers = {**self.author, "Idempotency-Key": "manual-retry"}
        self.assertEqual(self.client.post(url, headers=retry_headers).json()["job"]["status"], "queued")
        with self.session() as db:
            self.assertEqual(db.query(GenerationJob).count(), 2)
            self.assertEqual(quota_for(db, 1)["used"], 1)

    def test_unstarted_content_refund_uses_original_utc_day_and_exact_charge(self):
        today = int(datetime.now(timezone.utc).timestamp()) // DAY
        yesterday = today - 1
        scopes = (("site_generation", "all"), ("user_generation", "1"))
        with self.session.begin() as db:
            for window, previous in ((yesterday, (4, 1)), (today, (7, 2))):
                for (scope, subject), used in zip(scopes, previous):
                    db.add(WindowCounter(scope=scope, subject=subject, window=window, used=used,
                                         expires=(window + 1) * DAY))
        task_id = self.make_task(TaskStatus.OUTLINE_GENERATED, outline="Outline", outline_confirmed=True)
        with patch("src.blog_agent.service.quota_service.time") as clock, patch.object(settings, "agent_job_max_attempts", 1):
            clock.time.return_value = today * DAY - 1
            response = self.client.post(f"/api/v1/task/{task_id}/generate-content", headers=self.author)
            self.assertEqual(response.status_code, 200, response.text)
        claim = self.claim()
        with self.session() as db:
            mark = db.get(GenerationReservation, claim.job_id)
            self.assertEqual((mark.window, mark.units), (yesterday, 3))
            self.assertEqual([db.get(WindowCounter, (*key, yesterday)).used for key in scopes], [7, 4])
            job_queue.begin_execution(db, claim)
            db.rollback()  # A crashed worker with no committed execution still qualifies.
        self.expire(claim)
        self.assertIsNone(self.claim())
        with self.session() as db:
            self.assertEqual([db.get(WindowCounter, (*key, yesterday)).used for key in scopes], [4, 1])
            self.assertEqual([db.get(WindowCounter, (*key, today)).used for key in scopes], [7, 2])

    def test_legacy_job_without_record_does_not_invent_a_refund(self):
        with patch.object(settings, "agent_job_max_attempts", 1):
            self.assertEqual(self.submit_title(self.make_task()).status_code, 200)
        claim = self.claim()
        with self.session.begin() as db:
            db.delete(db.get(GenerationReservation, claim.job_id))
        self.expire(claim)
        self.assertIsNone(self.claim())
        with self.session() as db:
            job = db.get(GenerationJob, claim.job_id)
            self.assertEqual(job.status, "failed")
            self.assertNotIn("已退回", db.get(BlogTask, job.task_id).error)
            self.assertEqual(quota_for(db, 1)["used"], 1)

    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL row locks")
    def test_two_recoveries_only_refund_the_one_unstarted_job(self):
        self.assertEqual(self.submit_title(self.make_task()).status_code, 200)
        previous = self.claim()
        with self.session.begin() as db:
            job_queue.begin_execution(db, previous)
        with self.session.begin() as db:
            job_queue.abandon(db, previous)
        with patch.object(settings, "agent_job_max_attempts", 1):
            self.assertEqual(self.submit_title(self.make_task()).status_code, 200)
        claim = self.claim()
        barrier = Barrier(2)

        def recover(_):
            barrier.wait(timeout=5)
            try:
                with self.session.begin() as db:
                    job_queue.abandon(db, claim)
                return True
            except job_queue.LeaseLost:
                return False

        with ThreadPoolExecutor(2) as replicas:
            self.assertEqual(sorted(replicas.map(recover, range(2))), [False, True])
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 1)
            self.assertEqual(db.query(WindowCounter).filter_by(scope="site_generation").one().used, 1)

    def test_started_attempt_never_replays_and_late_writes_cannot_overwrite_a_retry(self):
        task_id = self.make_task()
        self.submit_title(task_id)
        first = self.claim()
        with self.session.begin() as db:
            job_queue.begin_execution(db, first)
        with self.session() as db:
            self.assertIsNone(db.get(GenerationReservation, first.job_id))
        self.expire(first)
        self.assertIsNone(self.claim())
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 1)
        self.assertEqual(self.submit_title(task_id).json()["job"]["status"], "queued")
        with self.assertRaises(job_queue.LeaseLost), job_queue.fenced_writes(first), self.session() as db:
            TaskService.save_titles(db, task_id, ["stale"])
        with self.assertRaises(job_queue.LeaseLost), job_queue.fenced_writes(first), self.session() as db:
            TaskService.mark_failed(db, task_id, "stale error")
        with self.session() as db:
            task = db.get(BlogTask, task_id)
            self.assertIsNone(task.titles)
            self.assertIsNone(task.error)
            self.assertEqual(task.status, TaskStatus.RESEARCHING_TITLE)
            self.assertEqual(job_queue.active_jobs(db, 1), 1)

    def test_capacity_rejection_rolls_back_changes_and_quota(self):
        first = self.make_task()
        second = self.make_task(TaskStatus.COMPLETED, content="published", is_public=True)
        self.assertEqual(self.submit_title(first).status_code, 200)
        with patch.object(settings, "free_max_active_jobs", 1):
            denied = self.submit_title(second)
            self.assertEqual(denied.json()["detail"]["code"], "active_job_limit")
        with patch.object(settings, "free_max_active_jobs", 4), patch.object(settings, "agent_max_queued_jobs", 1):
            denied = self.submit_title(second)
            self.assertEqual(denied.json()["detail"]["code"], "queue_full")
        with self.session() as db:
            saved = db.get(BlogTask, second)
            self.assertEqual((saved.content, saved.is_public, saved.status), ("published", True, TaskStatus.COMPLETED))
            self.assertEqual(quota_for(db, 1)["used"], 1)
            self.assertEqual(db.query(GenerationJob).count(), 1)

    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL row and advisory locks")
    def test_committed_replay_and_known_denials_do_not_wait_on_writers(self):
        first = self.make_task()
        second = self.make_task()
        url = f"/api/v1/task/{first}/generate-titles"
        headers = {**self.author, "Idempotency-Key": "accepted-click"}
        self.assertEqual(self.client.post(url, headers=headers).status_code, 200)
        with ThreadPoolExecutor(1) as requests:
            with self.session.begin() as editing, patch.object(settings, "free_max_active_jobs", 4):
                editing.get(BlogTask, first, with_for_update=True)
                job_queue.queue_lock(editing)
                replay = requests.submit(self.client.post, url, headers=headers).result(timeout=3)
                self.assertEqual(replay.json()["job"]["status"], "queued")
                with patch.object(settings, "agent_max_queued_jobs", 1):
                    full = requests.submit(self.submit_title, second).result(timeout=3)
                    self.assertEqual(full.json()["detail"]["code"], "queue_full")
                with patch.object(settings, "site_daily_units", 1):
                    exhausted = requests.submit(self.submit_title, second).result(timeout=3)
                    self.assertEqual(exhausted.json()["detail"]["code"], "site_daily_limit")
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 1)
            self.assertEqual(db.query(GenerationJob).count(), 1)

    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL advisory locks")
    def test_multiple_instances_obey_site_wide_worker_cap(self):
        with patch.object(settings, "free_max_active_jobs", 4):
            for _ in range(4):
                self.assertEqual(self.submit_title(self.make_task()).status_code, 200)
        barrier = Barrier(4)

        def claim_concurrently(_):
            barrier.wait(timeout=10)
            return self.claim()

        with patch.object(settings, "agent_max_workers", 2), ThreadPoolExecutor(4) as replicas:
            claims = [claim.job_id for claim in replicas.map(claim_concurrently, range(4)) if claim]
        self.assertEqual(len(set(claims)), 2)
        self.assertEqual(len(claims), 2)

    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL admission lock")
    def test_overlapping_submissions_on_different_manuscripts_share_account_limit(self):
        task_ids = [self.make_task(), self.make_task()]
        barrier = Barrier(2)

        def submit(task_id):
            barrier.wait(timeout=10)
            return self.submit_title(task_id).status_code

        with patch.object(settings, "free_max_active_jobs", 1), ThreadPoolExecutor(2) as requests:
            results = sorted(requests.map(submit, task_ids))
        self.assertEqual(results, [200, 429])
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 1)

    def test_pending_stream_ends_immediately_and_releases_account_slot(self):
        url = f"/api/v1/task/{self.make_task()}/stream"
        with patch("src.blog_agent.db.session.SessionLocal", self.session):
            for _ in range(4):
                response = self.client.get(url, headers=self.author)
                self.assertEqual(response.status_code, 200)
                self.assertIn("event: done", response.text)

    @unittest.skipUnless(os.getenv("POSTGRES_TEST_URL"), "requires PostgreSQL statement snapshots")
    def test_progress_read_observes_one_commit_across_worker_completion(self):
        task_id = self.make_task()
        self.assertEqual(self.submit_title(task_id).status_code, 200)
        claim = self.claim()
        engine = self.session.kw["bind"]
        transitions = []

        def complete_after_select(conn, cursor, statement, parameters, context, executemany):
            if transitions or not statement.startswith("SELECT blog_task.") or "FROM blog_task" not in statement:
                return
            # The current SELECT is already pinned to its snapshot. Complete the
            # job before the API has a chance to issue a second read.
            transitions.append(claim.job_id)
            with self.session.begin() as db:
                db.get(BlogTask, task_id).status = TaskStatus.TITLE_GENERATED
                db.get(GenerationJob, claim.job_id).status = "succeeded"

        event.listen(engine, "after_cursor_execute", complete_after_select)
        try:
            response = self.client.get(f"/api/v1/task/{task_id}", headers=self.author)
        finally:
            event.remove(engine, "after_cursor_execute", complete_after_select)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(transitions, [claim.job_id])
        data = response.json()
        self.assertEqual((data["status"], data["job"]["status"]), ("researching_title", "running"))
        next_read = self.client.get(f"/api/v1/task/{task_id}", headers=self.author).json()
        self.assertEqual((next_read["status"], next_read["job"]["status"]), ("title_generated", "succeeded"))

    def test_offline_upgrade_only_recovers_old_untracked_work(self):
        legacy = self.make_task(TaskStatus.RESEARCHING_CONTENT, outline="B", outline_confirmed=True)
        done = self.make_task(TaskStatus.COMPLETED, formatted_content="keep")
        active = self.make_task()
        self.submit_title(active)
        with self.session.begin() as db:
            self.assertEqual(job_queue.recover_legacy(db, apply=False), 1)
            self.assertEqual(db.get(BlogTask, legacy).status, TaskStatus.RESEARCHING_CONTENT)
            self.assertEqual(job_queue.recover_legacy(db, apply=True), 1)
        with self.session() as db:
            self.assertEqual(db.get(BlogTask, done).formatted_content, "keep")
            self.assertEqual(db.get(BlogTask, legacy).status, TaskStatus.FAILED)
            self.assertTrue(db.get(BlogTask, legacy).outline_confirmed)
            self.assertEqual(job_queue.latest_job(db, active)["status"], "queued")

    def test_stream_limit_is_per_account_and_slot_is_reusable(self):
        task_id = self.make_task()
        with self.session() as db:
            owner = db.get(fixtures.User, 1)
        slots = [_stream_slot(owner) for _ in range(3)]
        try:
            for slot in slots:
                next(slot)
            url = f"/api/v1/task/{task_id}/stream"
            response = self.client.get(url, headers=self.author)
            self.assertEqual(response.status_code, 429)
            self.assertEqual(self.client.get(url, headers=self.reader).status_code, 403)
            slots.pop().close()
            with patch("src.blog_agent.db.session.SessionLocal", self.session):
                self.assertEqual(self.client.get(url, headers=self.author).status_code, 200)
        finally:
            for slot in slots:
                slot.close()

    def test_readiness_needs_a_healthy_supervisor_and_database(self):
        from src.blog_agent.main import ready
        from src.blog_agent.db.session import get_db

        self.app.add_api_route("/api/v1/ready", ready)
        url = "/api/v1/ready"
        self.assertEqual(self.client.get(url).status_code, 503)
        self.app.state.supervisor = Mock(ready=True)
        self.assertEqual(self.client.get(url).json(), {"status": "ready"})
        unavailable = Mock()
        unavailable.execute.side_effect = OperationalError("", {}, Exception("internal details"))
        self.app.dependency_overrides[get_db] = lambda: unavailable
        response = self.client.get(url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("internal details", response.text)
