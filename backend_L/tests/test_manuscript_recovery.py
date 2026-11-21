"""Exercise recovery through the authenticated HTTP workflow on a failed rewrite."""
from unittest.mock import patch

import test_api_workflow as fixtures
from config.settings import settings
from src.blog_agent.db.models import BlogTask, ManuscriptBackup, TaskStatus
from src.blog_agent.service import job_queue
from src.blog_agent.service.quota_service import quota_for


class ManuscriptRecoveryTests(fixtures.DatabaseCase):
    def test_progress_change_does_not_acknowledge_another_tabs_command(self):
        task_id = self.make_task()
        path = f"/api/v1/task/{task_id}"
        sent = {**self.author, "Idempotency-Key": "second-tab"}
        missing = {**self.author, "Idempotency-Key": "lost-first-request"}
        self.assertEqual(self.client.post(path + "/generate-titles", headers=sent).status_code, 200)
        self.interrupt_started_stage()
        self.assertIsNone(self.client.get(path, headers=missing).json()["accepted_request_key"])
        ack = self.client.get(path, headers=sent).json()
        self.assertEqual((ack["status"], ack["accepted_request_key"]), ("failed", "second-tab"))
        self.assertEqual(self.client.get(path, headers={**self.reader, "Idempotency-Key": "second-tab"}).status_code, 403)
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 1)

    def interrupt_started_stage(self):
        with self.session.begin() as db:
            claim = job_queue.claim_next(db)
        with self.session.begin() as db:
            job_queue.begin_execution(db, claim)
        with self.session.begin() as db:
            job_queue.abandon(db, claim)

    def test_interrupted_rewrite_restores_the_complete_private_edition_without_cost(self):
        for action, cost in (("generate-titles", 1), ("generate-content", 3)):
            with self.subTest(action=action):
                task_id = self.make_task(
                    TaskStatus.COMPLETED, titles='["First title"]', selected_title="First title",
                    outline="Approved outline", outline_confirmed=True, word_count=600, level="advanced",
                    content="Prior draft", formatted_content="# Saved edition", review_feedback='{"score":91}',
                    image_urls='["/images/saved.png"]', is_public=True, allow_download=True, download_price=2,
                )
                path = f"/api/v1/task/{task_id}"
                key = {**self.author, "Idempotency-Key": "rewrite"}
                with self.session() as db:
                    initial = quota_for(db, 1)["used"]
                self.assertEqual(self.client.post(path + "/" + action, headers=key).status_code, 200)
                self.assertEqual(self.client.post(path + "/restore-previous", headers=self.author).status_code, 409)
                self.interrupt_started_stage()
                failed = self.client.get(path, headers=self.author).json()
                self.assertEqual(failed["status"], "failed")
                self.assertTrue(failed["can_restore_previous"])
                self.assertEqual(self.client.post(path + "/restore-previous", headers=self.reader).status_code, 403)
                with self.session() as db:
                    self.assertEqual(quota_for(db, 1)["active_jobs"], 0)
                restored = self.client.post(path + "/restore-previous", headers=self.author)
                self.assertEqual(restored.status_code, 200)
                task = self.client.get(path, headers=self.author).json()
                self.assertEqual((task["status"], task["formatted_content"]), ("completed", "# Saved edition"))
                self.assertEqual((task["selected_title"], task["outline"], task["word_count"], task["level"]),
                                 ("First title", "Approved outline", 600, "advanced"))
                self.assertEqual(task["review_result"]["score"], 91)
                self.assertEqual(task["image_urls"], ["/images/saved.png"])
                self.assertFalse(task["is_public"] or task["allow_download"] or task["download_price"])
                self.assertFalse(task["can_restore_previous"])
                self.assertIsNone(task["job"])
                replay = self.client.post(path + "/" + action, headers=key)
                self.assertEqual(replay.json()["formatted_content"], "# Saved edition")
                with self.session() as db:
                    self.assertEqual(quota_for(db, 1)["used"], initial + cost)

    def test_outline_backup_survives_two_failures_and_rejected_admission(self):
        task_id = self.make_task(TaskStatus.OUTLINE_GENERATED, selected_title="Chosen", outline="Edited outline",
                                 outline_confirmed=True, word_count=880, content_extra_requirements="Keep examples")
        path = f"/api/v1/task/{task_id}"
        for n in range(2):
            reply = self.client.post(path + "/regenerate-outline",
                                     headers={**self.author, "Idempotency-Key": f"try-{n}"})
            self.assertEqual(reply.status_code, 200)
            self.interrupt_started_stage()
        with patch.object(settings, "free_daily_units", 2):
            self.assertEqual(self.client.post(path + "/regenerate-outline", headers=self.author).status_code, 429)
        restored = self.client.post(path + "/restore-previous", headers=self.author).json()
        self.assertEqual((restored["outline"], restored["word_count"], restored["content_extra_requirements"]),
                         ("Edited outline", 880, "Keep examples"))
        self.assertTrue(restored["outline_confirmed"])
        with self.session() as db:
            self.assertEqual(quota_for(db, 1)["used"], 2)

    def test_latest_written_draft_survives_another_failure_before_writing(self):
        task_id = self.make_task(TaskStatus.FAILED, outline="Confirmed", outline_confirmed=True,
                                 content_research="First research")
        path = f"/api/v1/task/{task_id}"
        for wrote_draft in (True, False):
            self.assertEqual(self.client.post(path + "/generate-content", headers=self.author).status_code, 200)
            if wrote_draft:
                # The writer saved its draft before the process died during review.
                with self.session.begin() as db:
                    db.get(BlogTask, task_id).content = "Draft awaiting review"
            self.interrupt_started_stage()
        recovered = self.client.post(path + "/restore-previous", headers=self.author)
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["content"], "Draft awaiting review")
        self.assertEqual(recovered.json()["status"], "failed")
        self.assertIsNone(recovered.json()["formatted_content"])

    def test_successful_replacement_removes_the_recovery_copy_at_commit(self):
        task_id = self.make_task(TaskStatus.TITLE_GENERATED, titles='["Old title"]')
        path = f"/api/v1/task/{task_id}"
        self.assertEqual(self.client.post(path + "/generate-titles", headers=self.author).status_code, 200)
        with self.session.begin() as db:
            self.assertIsNotNone(db.get(ManuscriptBackup, task_id))
            claim = job_queue.claim_next(db)
        with self.session.begin() as db:
            job_queue.begin_execution(db, claim)
        with job_queue.fenced_writes(claim), self.session.begin() as db:
            task = db.get(BlogTask, task_id)
            task.titles, task.status = '["Replacement"]', TaskStatus.TITLE_GENERATED
        with self.session() as db:
            self.assertIsNone(db.get(ManuscriptBackup, task_id))
        self.assertEqual(self.client.post(path + "/restore-previous", headers=self.author).status_code, 409)

    def test_restoring_failed_body_does_not_reopen_failed_title_attempt(self):
        task_id = self.make_task(TaskStatus.FAILED, content="Saved body", selected_title="Title",
                                 outline="Outline", outline_confirmed=True)
        path = f"/api/v1/task/{task_id}"
        self.assertEqual(self.client.post(path + "/generate-titles", headers=self.author).status_code, 200)
        self.interrupt_started_stage()
        restored = self.client.post(path + "/restore-previous", headers=self.author).json()
        self.assertEqual((restored["status"], restored["outline_confirmed"], restored["content"]),
                         ("failed", True, "Saved body"))
        self.assertIsNone(restored["job"])
