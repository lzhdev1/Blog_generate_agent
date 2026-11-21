"""Used only by isolated_http.py --worker-recovery in its private Linux PID namespace."""

import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Barrier, Event, Lock, Thread
from time import monotonic, sleep
from uuid import uuid4

import requests
from sqlalchemy import func

from src.blog_agent.db.job_models import GenerationJob, GenerationRequest, GenerationReservation
from src.blog_agent.db.access_models import WindowCounter
from src.blog_agent.db.models import BlogTask, User
from src.blog_agent.db.session import SessionLocal, init_db
from src.blog_agent.service.auth_service import create_access_token


def wait(check, timeout=30, interval=0.025):
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        result = check()
        if result:
            return result
        sleep(interval)
    raise TimeoutError(check.__name__)


def elapsed(since):
    return round(monotonic() - since, 3)


class Model:
    def __init__(self, fixture):
        self.counts, self.gates, lock = Counter(), {}, Lock()
        calls, gates = self.counts, self.gates

        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                marker, = set(re.findall(r"CASE\d{3}", json.dumps(data["messages"])))
                content, _ = fixture(data, marker)
                with lock:
                    calls[marker] += 1
                    gate = gates.get(marker)
                if gate and not gate.wait(60):
                    raise TimeoutError("Fixture model request was never released")
                message = {"role": "assistant", "content": content}
                body = json.dumps({"model": "offline", "choices": [
                    {"index": 0, "message": message, "finish_reason": "stop"}
                ]}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The test terminated the caller while its response was pending.

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 17871), Endpoint)
        Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        for gate in self.gates.values():
            gate.set()
        self.server.shutdown()
        self.server.server_close()


class Replica:
    def __init__(self, port, *, slow=False, lease_seconds=5, env_overrides=None):
        self.base = f"http://127.0.0.1:{port}/api/v1"
        env = {**os.environ, "AGENT_QUEUE_POLL_SECONDS": "8" if slow else "0.12",
               "AGENT_JOB_LEASE_SECONDS": "24" if slow else str(lease_seconds), **(env_overrides or {})}
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.blog_agent.main:app", "--host", "127.0.0.1",
             "--port", str(port), "--no-access-log", "--log-level", "warning"],
            env=env, stdin=subprocess.DEVNULL,
        )

    def ready(self):
        if self.process.poll() is not None:
            raise RuntimeError("Test API exited")
        try:
            return requests.get(self.base + "/ready", timeout=0.4).ok
        except requests.RequestException:
            return False

    def stop(self, *, crash=False):
        if self.process.poll() is None:
            (self.process.kill if crash else self.process.terminate)()
            self.process.wait(timeout=10)
        return monotonic()

    def request(self, method, path, headers, **kwargs):
        res = requests.request(method, self.base + path, headers=headers, timeout=5, **kwargs)
        assert res.status_code == 200, (path, res.status_code, res.text[:256])
        return res.json()


class Manuscript:
    def __init__(self, marker, api, headers=None, *, submit=True):
        if headers is None:
            with SessionLocal.begin() as db:
                user = User(username=marker, nickname=marker, email=marker + "@example.test",
                            email_verified=True, password_hash="test")
                db.add(user)
                db.flush()
                headers = {"Authorization": "Bearer " + create_access_token(user.id)}
        self.headers = headers
        self.marker = marker
        self.key = "stage-" + uuid4().hex
        self.id = api.request("POST", "/task", headers, json={"topic": marker + " author notes"})["id"]
        if submit:
            assert self.submit(api, self.key)["job"]["status"] == "queued"

    def submit(self, api, key):
        headers = {**self.headers, "Idempotency-Key": key}
        return api.request("POST", f"/task/{self.id}/generate-titles", headers)

    def job(self):
        with SessionLocal() as db:
            return (db.query(GenerationJob.id, GenerationJob.attempt, GenerationJob.status, GenerationJob.started_at,
                             GenerationJob.lease_until, GenerationJob.finished_at, BlogTask.status.label("task_status"),
                             func.clock_timestamp().label("db_now")).join(BlogTask, BlogTask.id == GenerationJob.task_id)
                    .filter(GenerationJob.task_id == self.id).order_by(GenerationJob.id.desc()).first())

    def terminal(self, api, status, attempt, *, used=1, jobs=1):
        def finished():
            row = self.job()
            if row.status in ("succeeded", "failed"):
                assert (row.status, row.attempt) == (status, attempt), row
                return row
        row = wait(finished)
        quota = api.request("GET", "/auth/quota", self.headers)
        assert (quota["used"], quota["active_jobs"]) == (used, 0), quota
        replay = self.submit(api, self.key)  # Replaying an old accepted key returns the current task.
        assert replay["job"]["status"] == status and replay["status"] == row.task_status.value, replay
        with SessionLocal() as db:
            assert db.query(GenerationJob).filter_by(task_id=self.id).count() == jobs
            assert db.query(GenerationRequest).filter_by(task_id=self.id).count() == jobs
            assert db.get(GenerationReservation, row.id) is None
        return row

    def owned_worker(self, api, attempt, *, started):
        def find():
            row = self.job()
            if row.status != "running" or row.attempt != attempt:
                return
            assert (row.started_at is not None) == started, "Missed requested worker fault boundary"
            for path in Path("/proc").iterdir():
                if not path.name.isdecimal():
                    continue
                try:
                    fd = os.pidfd_open(int(path.name))
                except ProcessLookupError:
                    continue
                try:
                    stat = (path / "stat").read_text().rsplit(")", 1)[1].split()
                    argv = (path / "cmdline").read_bytes().split(b"\0")
                    if (int(stat[1]) == api.process.pid and
                            argv[1:4] == [b"-m", b"src.blog_agent.service.job_worker", str(row.id).encode()]):
                        return os.dup(fd)
                except (FileNotFoundError, ProcessLookupError):
                    pass
                finally:
                    os.close(fd)
        return wait(find, interval=0.005)

    def crash(self, api, attempt, *, started, whole_api=False):
        import select
        fd = self.owned_worker(api, attempt, started=started)
        try:
            tick = monotonic()
            if whole_api:
                api.stop(crash=True)
                assert select.select([fd], [], [], 4)[0], "Orphaned worker survived its supervisor"
            else:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            return tick
        finally:
            os.close(fd)


def exercise(fixture):
    init_db()
    model = Model(fixture)
    replicas, results = [], []

    def start(port, slow=False):
        api = Replica(port, slow=slow)
        replicas.append(api)
        wait(api.ready)
        return api

    def record(case, marker, calls, **values):
        assert model.counts[marker] == calls, (case, model.counts)
        results.append(dict(case=case, model_calls=calls, **values))

    try:
        first, second = 17870, 17872
        api = start(first, slow=True)
        draft = Manuscript("CASE001", api)
        assert (draft.job().status, draft.job().attempt) == ("queued", 0) and not model.counts["CASE001"]
        tick = api.stop(crash=True)
        api = start(second)
        draft.terminal(api, "succeeded", 1)
        baseline = model.counts["CASE001"]
        assert baseline == 5
        record("queued_survives_replacement", "CASE001", baseline, attempt=1, used=1, recovery_s=elapsed(tick))

        draft = Manuscript("CASE002", api)
        tick = draft.crash(api, 1, started=False)
        draft.terminal(api, "succeeded", 2)
        record("unstarted_worker_reclaimed", "CASE002", baseline, attempt=2, used=1, recovery_s=elapsed(tick))

        draft = Manuscript("CASE003", api)
        assert api.request("GET", "/auth/quota", draft.headers)["used"] == 1
        first_kill = draft.crash(api, 1, started=False)
        tick = draft.crash(api, 2, started=False)
        draft.terminal(api, "failed", 2, used=0)
        assert "已退回" in draft.submit(api, draft.key)["error"]
        record("two_unstarted_workers_exhausted", "CASE003", 0, attempt=2, used=0,
               reclaim_s=round(tick - first_kill, 3), recovery_s=elapsed(tick))
        assert draft.submit(api, "manual-" + uuid4().hex)["job"]["status"] == "queued"
        draft.terminal(api, "succeeded", 1, jobs=2)
        record("explicit_retry_after_refund", "CASE003", baseline, attempt=1, used_history=[1, 0, 1])

        for marker, mode in (("CASE004", "worker"), ("CASE005", "peer"), ("CASE006", "offline")):
            model.gates[marker] = Event()
            draft = Manuscript(marker, api)
            wait(lambda: model.counts[marker] == 1)
            if mode == "peer":
                peer = start(first)
            tick = draft.crash(api, 1, started=True, whole_api=mode != "worker")
            child_exit = elapsed(tick)
            lease = draft.job().lease_until
            timings = {}
            if mode == "peer":
                api = peer
            if mode == "offline":
                sleep(12)  # No survivor, more than two of the configured 5-second leases.
                row = draft.job()
                assert row.status == "running" and row.db_now > lease
                timings["offline_s"] = elapsed(tick)
                tick = monotonic()
                api = start(second)
            row = draft.terminal(api, "failed", 1)
            timings["recovery_s"] = elapsed(tick)
            if mode != "worker":
                timings.update(child_exit_s=child_exit, after_lease_s=round((row.finished_at - lease).total_seconds(), 3))
            record("started_model_interrupted_" + mode, marker, 1, attempt=1, used=1, **timings)
            model.gates[marker].set()

        draft = Manuscript("CASE007", api, headers=draft.headers)
        draft.terminal(api, "succeeded", 1, used=2)
        record("same_account_next_submission", "CASE007", baseline, attempt=1, used=2)

        draft = Manuscript("CASE008", api)
        tick = draft.crash(api, 1, started=False, whole_api=True)
        previous = draft.job()
        assert previous.started_at is None and not model.counts["CASE008"]
        api = start(first)
        row = draft.terminal(api, "succeeded", 2)
        record("unstarted_api_replaced", "CASE008", baseline, attempt=2, used=1, recovery_s=elapsed(tick),
               begin_after_lease_s=round((row.started_at - previous.lease_until).total_seconds(), 3))
        with SessionLocal() as db:
            assert db.query(GenerationJob).filter(GenerationJob.status.in_(("queued", "running"))).count() == 0
        print(json.dumps(dict(passed=len(results), lease_s=5, max_attempts=2, cases=results)), flush=True)
    finally:
        for api in replicas:
            api.stop()
        model.close()


def exercise_survivor(fixture):
    """Keep the second replica available while the first replica's running lease expires."""
    init_db()
    model = Model(fixture)
    replicas = []
    samples = []
    stop_reads = Event()
    started_stream = Event()

    def start(port):
        api = Replica(port, lease_seconds=15)
        replicas.append(api)
        wait(api.ready)
        return api

    def poll_author(api, draft):
        while not stop_reads.is_set():
            tick = monotonic()
            assert api.request("GET", "/ready", {}) == {"status": "ready"}
            task = api.request("GET", f"/task/{draft.id}", draft.headers)
            assert task["id"] == draft.id and draft.marker in task["topic"]
            listed = api.request("GET", "/my/articles", draft.headers)["items"]
            assert {row["task_id"] for row in listed} == {draft.id}
            quota = api.request("GET", "/auth/quota", draft.headers)
            assert quota["used"] == 1 and quota["active_jobs"] in (0, 1)
            samples.append(elapsed(tick))
            stop_reads.wait(0.2)

    def stream_author(api, draft):
        path = api.base + f"/task/{draft.id}/stream"
        states = []
        with requests.get(path, headers=draft.headers, stream=True, timeout=(3, 55)) as res:
            res.raise_for_status()
            for line in res.iter_lines(chunk_size=1):
                if line == b"event: done":
                    assert states[-1] == "succeeded", states
                    return states
                if line.startswith(b"data: "):
                    state = json.loads(line[6:])["job"]["status"]
                    if not states or state != states[-1]:
                        states.append(state)
                    started_stream.set()
        raise AssertionError("Missing terminal SSE event")

    executor = ThreadPoolExecutor(5)
    try:
        victim_api = start(17870)
        victim_marker = "CASE101"
        model.gates[victim_marker] = Event()
        victim = Manuscript(victim_marker, victim_api)
        wait(lambda: model.counts[victim_marker] == 1)
        live = start(17872)
        # These authors were preparing manuscripts while both replicas were healthy.
        drafts = [Manuscript(f"CASE{i}", live, submit=False) for i in range(102, 105)]
        for draft in drafts:
            model.gates[draft.marker] = Event()
        barrier = Barrier(3)

        def submit(draft):
            barrier.wait(timeout=5)
            tick = monotonic()
            assert draft.submit(live, draft.key)["job"]["status"] == "queued"
            return elapsed(tick)

        killed = victim.crash(victim_api, 1, started=True, whole_api=True)
        lost_lease = victim.job().lease_until
        late = Manuscript("CASE105", live, submit=False)
        drafts.append(late)
        model.gates[late.marker] = Event()
        latencies = list(executor.map(submit, drafts[:3]))
        queue = sorted(drafts[:3], key=lambda draft: draft.job().id)
        read_work = executor.submit(poll_author, live, queue[0])
        stream = executor.submit(stream_author, live, queue[2])
        assert started_stream.wait(8)
        # Replayed requests on the surviving replica consume no capacity.
        assert victim.submit(live, victim.key)["job"]["status"] == "running"
        assert all(draft.submit(live, draft.key)["job"]["status"] in ("running", "queued") for draft in queue)
        denied = requests.post(live.base + f"/task/{late.id}/generate-titles", timeout=4,
                               headers={**late.headers, "Idempotency-Key": late.key})
        assert (denied.status_code, denied.json()["detail"]["code"]) == (503, "queue_full")
        assert int(denied.headers["Retry-After"]) > 0
        assert live.request("GET", "/auth/quota", late.headers)["used"] == 0
        assert live.request("GET", f"/task/{late.id}", late.headers)["status"] == "pending"
        wait(lambda: model.counts[queue[0].marker] == 1)
        assert victim.job().status == "running" and queue[0].job().db_now < lost_lease
        assert [draft.job().status for draft in queue] == ["running", "queued", "queued"]
        until_available = elapsed(killed)
        failed = victim.terminal(live, "failed", 1)
        model.gates[victim_marker].set()
        assert model.counts[victim_marker] == 1
        assert late.submit(live, late.key)["job"]["status"] == "queued"
        wait(lambda: model.counts[queue[1].marker] == 1)
        assert [draft.job().status for draft in [*queue, late]] == ["running", "running", "queued", "queued"]
        model.gates[queue[0].marker].set()
        queue[0].terminal(live, "succeeded", 1)
        wait(lambda: model.counts[queue[2].marker] == 1)
        assert late.job().status == "queued"  # The newly admitted author stays behind prior admissions.
        for draft in [*queue[1:], late]:
            model.gates[draft.marker].set()
        for draft in [*queue[1:], late]:
            draft.terminal(live, "succeeded", 1)
        assert all(model.counts[draft.marker] == 5 for draft in drafts)
        states = stream.result(timeout=6)
        assert states[0] == "queued"
        stop_reads.set()
        read_work.result(timeout=6)
        with SessionLocal() as db:
            charges = db.query(WindowCounter).filter_by(scope="site_generation").one().used
            by_user = sorted(value for value, in db.query(WindowCounter.used).filter_by(scope="user_generation"))
            statuses = dict(db.query(GenerationJob.status, func.count()).group_by(GenerationJob.status).all())
            assert (charges, statuses) == (5, {"failed": 1, "succeeded": 4})
            assert by_user == [1] * 5
            assert db.query(GenerationRequest).count() == 5
            # The jobs' start/terminal commits were checked individually above.
            # The positive/negative markers rebuild their overlap on the database clock.
            events = sorted((moment, delta) for job in db.query(GenerationJob)
                            for moment, delta in ((job.started_at, 1), (job.finished_at, -1)))
            running = peak = 0
            for _, delta in events:
                running += delta
                peak = max(peak, running)
            assert peak == 2
        result = dict(
            passed=True, worker_cap=2, execution_peak=peak, capacity=4, lease_s=15, rejected_status=denied.status_code,
            draft_created_during_outage=late.marker,
            concurrent_submit_ms=[round(value * 1000) for value in latencies],
            normal_model_started_while_old_lease_live_s=until_available,
            recovery_after_lease_s=round((failed.finished_at - lost_lease).total_seconds(), 3),
            read_batches=len(samples), requests_per_read_batch=4, max_read_batch_ms=round(max(samples) * 1000),
            admission_and_claim_order=[draft.marker for draft in [*queue, late]], subscriber_states=states,
            old_job_calls=model.counts[victim_marker], normal_calls=sum(model.counts[draft.marker] for draft in drafts),
            user_usage=by_user, site_usage=charges, jobs=statuses, outage_observed_s=elapsed(killed),
        )
        print(json.dumps(result), flush=True)
    finally:
        stop_reads.set()
        for gate in model.gates.values():
            gate.set()
        for api in replicas:
            api.stop()
        executor.shutdown(wait=True)
        model.close()
