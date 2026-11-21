"""Supervise database-backed stage workers; each child can be stopped at its deadline."""
import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from config.settings import settings
from src.blog_agent.db.session import SessionLocal
from src.blog_agent.service import job_queue

log = logging.getLogger(__name__)


def execute_claim(claim, sessions=SessionLocal, stages=None):
    if stages is None:
        from src.blog_agent.service import agent_service
        stages = {
            "title": agent_service._run_title_stage,
            "outline": agent_service._run_outline_stage,
            "content": agent_service._run_content_stage,
        }
    with sessions.begin() as db:
        stage, args = job_queue.begin_execution(db, claim)
    if stage == "revision":
        from src.blog_agent.service.editorial import review_private_draft
        review_private_draft(claim, args[0], sessions=sessions)
        return
    with job_queue.fenced_writes(claim):
        stages[stage](*args)


@dataclass
class Child:
    process: subprocess.Popen
    started: float
    next_renewal: float


def _stop_child(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


class WorkerSupervisor:
    def __init__(self, sessions=SessionLocal):
        self.sessions = sessions
        self.children = {}
        self.stopping = threading.Event()
        self.last_successful_poll = None
        self.thread = threading.Thread(target=self._run, name="generation-supervisor", daemon=True)

    def start(self):
        self.thread.start()

    @property
    def ready(self):
        if self.stopping.is_set() or not self.thread.is_alive() or self.last_successful_poll is None:
            return False
        return time.monotonic() - self.last_successful_poll < max(15, settings.agent_queue_poll_seconds * 3)

    def stop(self):
        self.stopping.set()
        self.thread.join(timeout=8)

    def _abandon(self, claim):
        try:
            with self.sessions.begin() as db:
                job_queue.abandon(db, claim)
        except job_queue.LeaseLost:
            pass  # The final artifact was committed, or another worker already recovered it.

    def _monitor(self):
        now = time.monotonic()
        for claim, child in list(self.children.items()):
            if self.stopping.is_set() or now - child.started >= settings.agent_job_max_runtime_seconds:
                _stop_child(child.process)
            if child.process.poll() is not None:
                child.process.stdin.close()
                del self.children[claim]
                try:
                    self._abandon(claim)
                except Exception:
                    log.warning("Job %s will be recovered after its lease expires", claim.job_id)
                continue
            if now < child.next_renewal:
                continue
            try:
                with self.sessions.begin() as db:
                    job_queue.renew(db, claim)
                child.next_renewal = now + settings.agent_job_lease_seconds / 3
            except job_queue.LeaseLost:
                _stop_child(child.process)
                child.process.stdin.close()
                del self.children[claim]

    def _start_available(self):
        while not self.stopping.is_set() and len(self.children) < settings.agent_max_workers:
            with self.sessions.begin() as db:
                claim = job_queue.claim_next(db)
            if not claim:
                break
            env = dict(os.environ, GENERATION_CLAIM_TOKEN=claim.token)
            try:
                process = subprocess.Popen(
                    [sys.executable, "-m", "src.blog_agent.service.job_worker", str(claim.job_id)],
                    env=env, stdin=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except OSError:
                self._abandon(claim)
                log.exception("Could not start generation job %s", claim.job_id)
                break
            now = time.monotonic()
            self.children[claim] = Child(process, now, now + settings.agent_job_lease_seconds / 3)

    def _run(self):
        interval = min(settings.agent_queue_poll_seconds, settings.agent_job_lease_seconds / 3)
        try:
            while not self.stopping.is_set():
                try:
                    self._monitor()
                    self._start_available()
                    self.last_successful_poll = time.monotonic()
                except Exception:
                    log.exception("Generation queue unavailable; retrying")
                self.stopping.wait(interval)
        finally:
            # Stop all children before waiting for any DB writes during shutdown.
            for child in self.children.values():
                if child.process.poll() is None:
                    child.process.terminate()
            for claim, child in self.children.items():
                _stop_child(child.process)
                child.process.stdin.close()
                try:
                    self._abandon(claim)
                except Exception:
                    log.warning("Job %s will be recovered after its lease expires", claim.job_id)


def _watch_supervisor():
    # The supervisor owns the sole write end. Its hard termination closes this pipe
    # even when an in-flight SDK call never returns or the DB is unreachable.
    os.read(sys.stdin.fileno(), 1)
    os._exit(75)


if __name__ == "__main__":
    if sys.argv[1:2] == ["recover-legacy"]:
        parser = argparse.ArgumentParser(description="Inspect interrupted tasks after stopping all pre-queue services.")
        parser.add_argument("--apply", action="store_true", help="Mark interrupted legacy stages as failed for manual retry.")
        options = parser.parse_args(sys.argv[2:])
        with SessionLocal.begin() as db:
            count = job_queue.recover_legacy(db, apply=options.apply)
        print(f"{'Recovered' if options.apply else 'Found'} {count} interrupted legacy stages.")
    else:
        threading.Thread(target=_watch_supervisor, daemon=True).start()
        deadline = threading.Timer(settings.agent_job_max_runtime_seconds, os._exit, args=(75,))
        deadline.daemon = True
        deadline.start()
        try:
            execute_claim(job_queue.Claim(int(sys.argv[1]), os.environ.pop("GENERATION_CLAIM_TOKEN")))
        except job_queue.LeaseLost:
            sys.exit(0)
