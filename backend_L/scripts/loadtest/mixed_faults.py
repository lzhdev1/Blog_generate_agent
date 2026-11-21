"""Concurrent real HTTP flows, a replica crash, two provider faults and an independent audit."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from itertools import groupby
from pathlib import Path
import re
import secrets
import select
from threading import Barrier, Event, Lock, Thread
from time import monotonic, sleep

import requests

from mixed_audit import audit
from src.blog_agent.db.session import init_db
from worker_recovery import Replica, wait


def utc():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Provider:
    """Hold a writer at its real SDK request and record every received request, including aborted ones."""

    def __init__(self, fixture):
        self.holds = {}
        self.injecting, self.crashed = Event(), Event()
        self.counts, self.requests, self.errors, self.lock = Counter(), [], [], Lock()
        self.fault_times = {}
        model = self

        class Endpoint(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers["content-length"])))
                markers = set(re.findall(r"CASE\d{3}", json.dumps(data["messages"])))
                if self.path != "/v1/chat/completions" or len(markers) != 1:
                    model.errors.append(sorted(markers))
                    self.send_error(422)
                    return
                marker = markers.pop()
                content, kind = fixture(data, marker)
                with model.lock:
                    model.counts[marker, kind] += 1
                    number = model.counts[marker, kind]
                    model.requests.append(dict(utc=utc(), marker=marker, kind=kind, invocation=number))
                status = 200
                if marker in model.holds and kind == "writer" and number == 1:
                    arrived, release = model.holds[marker]
                    arrived.set()
                    if not release.wait(70):
                        model.errors.append("unreleased writer")
                if marker == "CASE000" and kind == "writer" and number == 1:
                    model.fault_times["writer_timeout_request_utc"] = utc()
                    model.injecting.set()
                    sleep(5.5)  # Replica B's SDK read timeout is 4s.
                    self.close_connection = True
                    return
                if marker == "CASE001" and kind == "ReviewResult" and number == 1:
                    model.fault_times["review_429_request_utc"] = utc()
                    model.injecting.set()
                    model.crashed.wait(2)
                    model.fault_times["review_429_response_utc"] = utc()
                    status = 429
                    response = {"error": {"message": "isolated fixture", "code": "rate_limit"}}
                else:
                    sleep(0.045)
                    response = {
                        "model": "offline",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {"role": "assistant", "content": content},
                            }
                        ],
                    }
                body = json.dumps(response).encode()
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass  # The original A-side caller died while reading.

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 17871), Endpoint)
        Thread(target=self.server.serve_forever, daemon=True).start()

    def totals(self, marker):
        with self.lock:
            return {kind: value for (name, kind), value in self.counts.items() if name == marker}

    def close(self):
        self.crashed.set()
        for _, release in self.holds.values():
            release.set()
        self.server.shutdown()
        self.server.server_close()


class Author:
    def __init__(self, index, api):
        self.marker = f"CASE{index:03d}"
        self.api = api
        self.client = requests.Session()
        self.accepted, self.used, self.observations = [], [], []
        self.started = monotonic()
        email = self.marker.lower() + "@example.com"
        code = self.req("POST", "/auth/send-code", {"email": email})["code"]
        password = secrets.token_hex(12) + "Q7"
        signup = self.req(
            "POST",
            "/auth/register",
            dict(
                email=email,
                nickname=self.marker,
                username=self.marker,
                password=password,
                confirm_password=password,
                email_code=code,
            ),
        )
        self.token = signup["access_token"]
        self.user_id = signup["user"]["id"]
        self.client.headers["Authorization"] = "Bearer " + self.token
        self.task = self.req("POST", "/task", {"topic": self.marker + " 验证主题"})["id"]
        self.path = f"/task/{self.task}"
        self.fault = ("writer_timeout", "reviewer_429")[index] if index < 2 else None

    def req(self, method, path, data=None, key=None):
        headers = {"Idempotency-Key": key} if key else {}
        response = self.client.request(method, self.api.base + path, json=data, headers=headers, timeout=8)
        if not response.ok:
            raise RuntimeError((self.marker, method, path, response.status_code, response.text[:250]))
        return response.json()

    def submit(self, action, data=None):
        key = secrets.token_hex(16)
        began = monotonic()
        item = self.req("POST", self.path + "/" + action, data, key)
        self.observations.append(
            dict(action=action, admitted_utc=utc(), latency_s=round(monotonic() - began, 3))
        )
        self.accepted.append(dict(key=key, action=action, data=data))
        return item

    def await_stage(self, expected):
        def done():
            result = self.req("GET", self.path)
            if result["status"] == "failed" and expected != "failed":
                raise AssertionError((self.marker, expected, result["error"]))
            if result["status"] == expected:
                assert result["job"]["status"] == ("failed" if expected == "failed" else "succeeded")
                return result

        result = wait(done, timeout=180, interval=0.15)
        self.observations.append(dict(status=expected, observed_utc=utc()))
        self.used.append(self.req("GET", "/auth/quota")["used"])
        return result

    def prepare(self, barrier):
        barrier.wait(timeout=45)
        self.submit("generate-titles")
        titles = self.await_stage("title_generated")
        self.submit(
            "submit-title-config",
            dict(title=titles["titles"][0], article_style="note", need_image=False),
        )
        outline = self.await_stage("outline_generated")
        self.confirmed = self.req(
            "POST",
            self.path + "/confirm-outline",
            dict(outline=outline["outline"], word_count=260, level="general"),
        )

    def finish(self, model):
        replay_counts = {}
        if self.fault:
            failed = self.await_stage("failed")
            expected = {"writer_timeout": "响应超时", "reviewer_429": "限流", "api_crash": "执行中断"}
            assert expected[self.fault] in failed["error"], (self.marker, failed["error"])
            assert (
                not failed["is_public"]
                and not failed.get("formatted_content")
                and not failed.get("review_result")
            )
            assert self.marker in failed["content_research"]
            if self.fault == "reviewer_429":
                assert self.marker in failed["content"] and self.marker in failed["writing_thoughts"]
            else:
                assert not failed.get("content")
            for field in (
                "selected_title",
                "outline",
                "outline_confirmed",
                "article_style",
                "word_count",
                "level",
            ):
                assert self.confirmed[field] == failed[field]
            before = model.totals(self.marker)
            replay = self.req("POST", self.path + "/generate-content", key=self.accepted[-1]["key"])
            assert replay["status"] == "failed" and replay["job"] == failed["job"]
            after = model.totals(self.marker)
            assert after == before
            replay_counts = dict(replay_before=before, replay_after=after)
            self.used.append(self.req("GET", "/auth/quota")["used"])
            self.observations.append(
                dict(
                    replayed_utc=utc(),
                    provider_requests=sum(before.values()),
                    failure=failed["error"],
                    draft_saved=bool(failed.get("content")),
                )
            )
            self.submit("generate-content")
        self.await_stage("completed")
        assert self.used == ([1, 2, 5, 5, 8] if self.fault else [1, 2, 5]), (self.marker, self.used)
        return dict(
            marker=self.marker,
            user_id=self.user_id,
            task=self.task,
            token=self.token,
            fault=self.fault,
            used=self.used,
            expected_jobs=len(self.accepted),
            accepted_requests=self.accepted,
            **replay_counts,
        )


def job_owners(replicas):
    """Read only direct worker subprocesses of known fixture API PIDs."""
    names = {replica.process.pid: name for name, replica in replicas.items()}
    owners = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            ppid = int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1])
            if ppid in names:
                argv = (entry / "cmdline").read_bytes().split(b"\0")
                if argv[1:3] == [b"-m", b"src.blog_agent.service.job_worker"]:
                    owners[int(argv[3])] = dict(replica=names[ppid], worker_pid=int(entry.name))
        except (FileNotFoundError, ProcessLookupError):
            pass
    return owners


def install_trace(db):
    with db.cursor() as cur:
        cur.execute("""
          CREATE TABLE mixed_trace(job_id int, task_id int, stage text, status text, attempt int, began bool);
          CREATE FUNCTION mixed_trace_job() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN
            IF TG_OP='INSERT' OR (OLD.status,OLD.started_at) IS DISTINCT FROM (NEW.status,NEW.started_at) THEN
              INSERT INTO mixed_trace VALUES(NEW.id,NEW.task_id,NEW.stage,NEW.status,NEW.attempt,NEW.started_at IS NOT NULL);
            END IF;
            RETURN NEW;
          END; $$;
          CREATE TRIGGER observe_mixed_jobs AFTER INSERT OR UPDATE ON generation_jobs
              FOR EACH ROW EXECUTE FUNCTION mixed_trace_job();
        """)


def query(db, stmt, params=()):
    with db.cursor() as cur:
        cur.execute(stmt, params)
        return cur.fetchall()


def exercise(args, fixture, db):
    init_db()
    install_trace(db)
    replicas, processes, authors, timeline = {}, [], [], {}
    model = Provider(fixture)
    stop_probe, probes = Event(), []

    def start(name):
        env = dict(
            AGENT_MAX_WORKERS="1" if name == "A" else str(args.workers),
            AGENT_QUEUE_POLL_SECONDS="0.10" if name == "A" else "0.65",
            MODEL_LIMIT_REQUEST_SECONDS="60" if name == "A" else "4",
        )
        replica = Replica(17870 if name == "A" else 17872, lease_seconds=6, env_overrides=env)
        processes.append(replica)
        wait(replica.ready)
        replicas[name] = replica
        return replica

    def probe_b():
        while not stop_probe.is_set():
            try:
                status = requests.get(replicas["B"].base + "/ready", timeout=1).status_code
            except requests.RequestException:
                status = 0
            probes.append((utc(), status))
            stop_probe.wait(0.2)

    try:
        a, b = start("A"), start("B")
        timeline["started_utc"] = utc()
        probe = Thread(target=probe_b, daemon=True)
        probe.start()
        with ThreadPoolExecutor(args.users) as pool:
            authors = list(pool.map(lambda i: Author(i, a if i % 2 == 0 else b), range(args.users)))
            barrier = Barrier(args.users)
            list(pool.map(lambda author: author.prepare(barrier), authors))
            timeline["all_outlines_confirmed_utc"] = utc()
            print("All authors confirmed their outlines.", flush=True)
            for author in authors:
                author.api = b  # Existing signed-in authors use the surviving API during the outage.

            # Discover ownership from real subprocesses. If B wins the first ordinary
            # candidate it finishes normally; the next candidate is tested after the slot drains.
            submitted = []
            for candidate in authors[2:-1]:
                entered, release = Event(), Event()
                model.holds[candidate.marker] = (entered, release)
                candidate.submit("generate-content")
                submitted.append(candidate)
                (job,) = query(
                    db,
                    "SELECT id FROM generation_jobs WHERE task_id=%s AND stage='content'",
                    (candidate.task,),
                )[0]
                owner = wait(lambda: job_owners(replicas).get(job), timeout=40)
                if owner["replica"] == "A":
                    assert entered.wait(25)
                    victim, victim_job = candidate, job
                    victim.fault = "api_crash"
                    break
                release.set()
                wait(
                    lambda: query(db, "SELECT status FROM generation_jobs WHERE id=%s", (job,))[0][0]
                    == "succeeded"
                )
            else:
                raise AssertionError("Could not acquire an A-owned ordinary writer")
            timeline["victim_writer_inflight_utc"] = utc()
            remaining = [author for author in authors if author not in submitted]
            batch = Barrier(len(remaining))

            def enter_body(author):
                batch.wait(timeout=20)
                return author.submit("generate-content")

            list(pool.map(enter_body, remaining))
            timeline["content_batch_admitted_utc"] = utc()
            assert model.injecting.wait(45), "Supplier fault did not overlap the held A writer"
            owners = job_owners(replicas)
            rows = query(
                db,
                """SELECT j.id,u.username,j.status,j.started_at IS NOT NULL FROM generation_jobs j
                                JOIN users u ON u.id=j.user_id WHERE j.status IN ('running','queued') ORDER BY j.id""",
            )
            at_kill = [dict(job=j, marker=m, status=s, begun=t, **owners.get(j, {})) for j, m, s, t in rows]
            assert [j for j, item in owners.items() if item["replica"] == "A"] == [victim_job], owners
            assert any(item.get("replica") == "B" and item["begun"] for item in at_kill), at_kill
            original_pid = a.process.pid
            child_fd = os.pidfd_open(owners[victim_job]["worker_pid"])
            try:
                timeline["kill_sent_utc"] = utc()
                a.stop(crash=True)
                timeline["a_exited_utc"] = utc()
                model.crashed.set()
                assert select.select([child_fd], [], [], 4)[0], "An A-owned writer survived SIGKILL"
                timeline["victim_worker_exited_utc"] = utc()
            finally:
                os.close(child_fd)
            release.set()
            assert a.process.returncode == -9
            print("A stopped during its writer and a separate B-side supplier fault.", flush=True)

            def progress_while_down():
                rows = query(
                    db,
                    """SELECT u.username,j.finished_at FROM generation_jobs j JOIN users u ON u.id=j.user_id
                  WHERE j.stage='content' AND j.status='succeeded' AND j.finished_at>=%s ORDER BY j.finished_at""",
                    (timeline["a_exited_utc"],),
                )
                return [
                    (m, t.isoformat(timespec="milliseconds"))
                    for m, t in rows
                    if m not in ("CASE000", "CASE001", victim.marker)
                ]

            survivor_completions = wait(progress_while_down, timeout=120, interval=0.15)
            # Both faults must be observed by their intended terminal state while only B is serving.
            broken = [authors[0].task, authors[1].task, victim.task]
            wait(
                lambda: query(
                    db,
                    """SELECT count(*) FROM generation_jobs WHERE task_id=ANY(%s)
                        AND stage='content' AND status='failed'""",
                    (broken,),
                )[0][0]
                == 3,
                timeout=120,
                interval=0.15,
            )
            survivor_completions = progress_while_down()
            assert b.ready()
            timeline["replacement_start_utc"] = utc()
            restored = start("A")
            timeline["replacement_ready_utc"] = utc()
            assert original_pid != restored.process.pid and b.ready()
            manifest = list(pool.map(lambda author: author.finish(model), authors))
        timeline["all_completed_utc"] = utc()
        stop_probe.set()
        probe.join(3)
        assert probes and all(code == 200 for _, code in probes) and not model.errors
        counters = {marker: model.totals(marker) for marker in {row["marker"] for row in model.requests}}
        audited = audit(manifest, counters, db, b.base)
        result_events = query(
            db,
            """SELECT pg_xact_commit_timestamp(e.xmin),job_id,u.username,e.stage,
               e.status,e.attempt,e.began FROM mixed_trace e JOIN generation_jobs j ON j.id=e.job_id
               JOIN users u ON u.id=j.user_id ORDER BY 1,job_id""",
        )
        state, peaks, events = {}, Counter(), []
        for stamp, job, marker, stage, status, attempt, began in result_events:
            events.append(
                dict(
                    utc=stamp.isoformat(timespec="microseconds"),
                    job=job,
                    marker=marker,
                    stage=stage,
                    status=status,
                    attempt=attempt,
                    began=began,
                )
            )
        for _, committed in groupby(events, key=lambda item: item["utc"]):
            state.update((item["job"], item["status"]) for item in committed)
            snapshot = Counter(state.values())
            for status in ("queued", "running"):
                peaks[status] = max(peaks[status], snapshot[status])
        assert 0 < peaks["running"] <= args.workers and peaks["queued"] > 0
        e2e = {}
        for author in authors:
            trace = [event for event in events if event["marker"] == author.marker]
            submitted = next(
                event["utc"] for event in trace if event["stage"] == "title" and event["status"] == "queued"
            )
            finished = next(
                event["utc"]
                for event in trace
                if event["stage"] == "content" and event["status"] == "succeeded"
            )
            e2e[author.marker] = round(
                (datetime.fromisoformat(finished) - datetime.fromisoformat(submitted)).total_seconds(), 3
            )
        downtime_probes = [
            point
            for point in probes
            if timeline["a_exited_utc"] <= point[0] < timeline["replacement_ready_utc"]
        ]
        assert downtime_probes
        report = dict(
            timeline=timeline,
            users=args.users,
            caps=dict(
                replica_a=1,
                replica_b=args.workers,
                shared_running_ceiling=args.workers,
                lease_s=6,
                sdk_retries=0,
                request_s_a=60,
                request_s_b=4,
            ),
            a_pid=original_pid,
            replacement_pid=restored.process.pid,
            b_pid=b.process.pid,
            crash_victim=victim.marker,
            supplier_fault_times=model.fault_times,
            at_kill=at_kill,
            survivor_completed_before_restart=survivor_completions,
            probes_b=dict(
                samples=len(probes),
                failures=0,
                while_a_unavailable=len(downtime_probes),
                first_while_down=downtime_probes[0][0],
                last_while_down=downtime_probes[-1][0],
            ),
            queue_commit_peaks=dict(peaks),
            title_admission_commit_to_final_content_commit_seconds=e2e,
            database_events=events,
            provider_requests=model.requests,
            author_observations={item.marker: item.observations for item in authors},
            audit=audited,
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        if not audited["passed"]:
            raise SystemExit("Independent post-run audit failed")
    finally:
        stop_probe.set()
        model.close()
        for replica in processes:
            replica.stop()
        for author in authors:
            author.client.close()
