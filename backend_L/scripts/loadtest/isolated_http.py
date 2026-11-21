"""Run: python backend_L/scripts/loadtest/isolated_http.py --users 10 --workers 3

The host needs Python 3.10+ (Windows also supports "py -3") and Linux Docker.
Prepare the images once from the repository root if they are missing:
  docker pull postgres:16-alpine
  docker build -t blog-agent-l-backendl:latest backend_L
Local src/config are mounted read-only; rebuild only after dependency changes.
Use --image to select that local image. Creates a fresh internal Docker network and
tmpfs PostgreSQL database. No port is published and the repository .env is never mounted.
The final JSON contains timings and anonymous per-user assertions for this run.
Use --worker-recovery to stop test workers and replicas at specific queue boundaries.
Use --survivor-traffic to check other authors' admissions, progress and quotas during an outage.
Use --mixed-faults to inject provider errors and restart a replica under concurrent load.
"""

import argparse
import concurrent.futures
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def docker(*args, **kwargs):
    result = subprocess.run(["docker", *args], **kwargs)
    if result.returncode:
        # Avoid putting a temporary database password or JWT secret into an error report.
        raise RuntimeError(f"docker {args[0]} exited with status {result.returncode}")
    return result


def isolated_run(args):
    backend = Path(__file__).resolve().parents[2]
    name = "folio-load-" + secrets.token_hex(6)
    password = secrets.token_hex(24)
    # Resolve local images before creating any resources. Never pull or deploy on behalf of the caller.
    for image in (args.image, "postgres:16-alpine"):
        docker("image", "inspect", image, stdout=subprocess.DEVNULL)
    label = "folio.loadtest=" + name
    docker("network", "create", "--internal", "--label", label, name, stdout=subprocess.DEVNULL)
    try:
        docker(
            "run",
            "--detach",
            "--label",
            label,
            "--rm",
            "--name",
            name + "-pg",
            "--network",
            name,
            "--network-alias",
            "isolatedpg",
            "--tmpfs",
            "/var/lib/postgresql/data:rw",
            "-e",
            "POSTGRES_DB=caseflow",
            "-e",
            "POSTGRES_PASSWORD=" + password,
            "postgres:16-alpine",
            "-c",
            "track_commit_timestamp=on",
            stdout=subprocess.DEVNULL,
        )
        env = dict(
            APP_ENV="test",
            REGISTRATION_MODE="test",
            EMAIL_CODE_DEFAULT="123456",
            JWT_SECRET=secrets.token_hex(32),
            LLM_API_KEY="offline-fixture",
            LLM_MODEL="offline",
            LLM_BASE_URL="http://127.0.0.1:17871/v1",
            DB_URL=f"postgresql+psycopg2://postgres:{password}@isolatedpg:5432/caseflow",
            AGENT_QUEUE_POLL_SECONDS="0.12",
            IMAGE_SAVE_DIR="/tmp/qa/images",
            PYTHONPATH="/app",
            AGENT_MAX_WORKERS=str(args.workers),
            AUTH_SEND_PER_IP=str(args.users + 2),
            AUTH_REGISTER_PER_IP=str(args.users + 2),
            PYTHONUNBUFFERED="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        if args.provider_faults:
            env.update(MODEL_LIMIT_REQUEST_SECONDS="2", MODEL_LIMIT_SDK_RETRIES="0")
        if args.mixed_faults:
            env.update(AGENT_JOB_LEASE_SECONDS="6", AGENT_JOB_MAX_RUNTIME_SECONDS="120",
                       MODEL_LIMIT_SDK_RETRIES="0", MODEL_LIMIT_REQUEST_SECONDS="4")
        if args.worker_recovery:
            env.update(AGENT_MAX_WORKERS="1", AGENT_JOB_MAX_ATTEMPTS="2", AGENT_JOB_LEASE_SECONDS="5",
                       AGENT_JOB_MAX_RUNTIME_SECONDS="90", MODEL_LIMIT_SDK_RETRIES="0")
        if args.survivor_traffic:
            env.update(AGENT_MAX_WORKERS="2", AGENT_MAX_QUEUED_JOBS="4", AGENT_JOB_LEASE_SECONDS="15",
                       AGENT_JOB_MAX_RUNTIME_SECONDS="120", MODEL_LIMIT_SDK_RETRIES="0")
        cmd = ["run", "--rm", "--label", label, "--name", name + "-app", "--network", name, "-w", "/tmp/qa"]
        for src, target in [
            (backend / "src", "/app/src"),
            (backend / "config", "/app/config"),
            (Path(__file__).resolve(), "/qa.py"),
            (Path(__file__).with_name("provider_faults.py").resolve(), "/provider_faults.py"),
            (Path(__file__).with_name("worker_recovery.py").resolve(), "/worker_recovery.py"),
        ]:
            cmd += ["--mount", f"type=bind,source={src},target={target},readonly"]
        for key, value in env.items():
            cmd += ["-e", f"{key}={value}"]
        if args.mixed_faults:
            for filename in ("mixed_faults.py", "mixed_audit.py"):
                src = Path(__file__).with_name(filename).resolve(strict=True)
                cmd += ["--mount", f"type=bind,source={src},target=/{filename},readonly"]
        if args.survivor_traffic:
            print("Starting isolated PostgreSQL and 2 test replicas; queue capacity 4, worker cap 2.", flush=True)
        elif args.worker_recovery:
            print("Starting isolated PostgreSQL and restartable test API instances; worker cap 1.", flush=True)
        else:
            print(f"Starting isolated PostgreSQL and 2 API instances for {3 if args.provider_faults else args.users} users; worker cap {args.workers}.", flush=True)
        docker(
            *cmd,
            args.image,
            "python",
            "/qa.py",
            "--inside",
            "--users",
            str(args.users),
            "--workers",
            str(args.workers),
            *(["--provider-faults"] if args.provider_faults else []),
            *(["--worker-recovery"] if args.worker_recovery else []),
            *(["--mixed-faults"] if args.mixed_faults else []),
            *(["--survivor-traffic"] if args.survivor_traffic else []),
        )
    finally:
        owned = docker(
            "ps", "-aq", "--filter", "label=" + label, capture_output=True, text=True
        ).stdout.split()
        if owned:
            docker("rm", "-f", *owned, stdout=subprocess.DEVNULL)
        docker("network", "rm", name, stdout=subprocess.DEVNULL)


def fixture(data, marker):
    titles = [marker + " 编写指南", marker + " 流程笔记", marker + " 编辑实践"]
    common = dict(passed=True, score=94, review_opinions=[], pass_reasons=["完成校验"])
    schema = data.get("response_format", {}).get("json_schema", {}).get("name", "")
    if schema == "TitleList":
        out = dict(titles=titles)
    elif schema == "TitleScoreList":
        out = dict(
            scores=[
                dict(title=t, accuracy=9, uniqueness=9, seo=9, total=9, pros=["清晰"], cons=["精简"])
                for t in titles
            ]
        )
    elif schema == "TitleReviewResult":
        out = dict(common, relevance=95, type_match=92, attractiveness=90)
    elif schema == "OutlineReviewResult":
        out = dict(common, structure_match=95, research_reference=92, completeness=93, image_marks=100)
    elif schema == "ReviewResult":
        out = dict(
            common,
            dimension_scores=dict(
                outline_compliance=95, relevance=95, style_match=93, research_usage=92, logic_flow=91
            ),
        )
    elif data.get("tools"):
        return marker + " 计划已完成", "research_plan"
    else:
        system = data["messages"][0]["content"]
        if "写手" in system:
            return (
                "=====写作思路=====\n"
                + marker
                + " 写作计划\n=====正文=====\n# "
                + titles[0]
                + "\n\n## "
                + marker
                + " 执行流程\n\n"
                + "文稿经过调研、写作和审核。" * 20
            ), "writer"
        if "大纲" in system and "调研员" not in system:
            return "## " + marker + " 执行流程\n阐明工作步骤。", "outliner"
        return marker + " 隔离验证资料。", "research_summary"
    return json.dumps(out, ensure_ascii=False), schema


def summarize(values):
    values = sorted(values)
    return {
        key: round(values[max(0, math.ceil(len(values) * fraction) - 1)], 3)
        for key, fraction in [("min", 0), ("p50", 0.50), ("p95", 0.95), ("max", 1)]
    }


def run_case(args):
    import requests
    import psycopg2
    from urllib.parse import urlsplit

    db_url = os.environ["DB_URL"]
    parsed = urlsplit(db_url)
    if not (
        parsed.hostname == "isolatedpg"
        and parsed.path == "/caseflow"
        and os.environ.get("APP_ENV") == "test"
        and Path.cwd() == Path("/tmp/qa")
        and os.environ.get("LLM_BASE_URL") == "http://127.0.0.1:17871/v1"
    ):
        raise RuntimeError("This harness only runs inside its disposable container.")
    database_dsn = db_url.replace("postgresql+psycopg2:", "postgresql:")
    for attempt in range(80):
        try:
            db = psycopg2.connect(database_dsn, connect_timeout=2)
            break
        except psycopg2.OperationalError:
            if attempt == 79:
                raise
            time.sleep(0.2)
    db.autocommit = True
    with db.cursor() as cur:
        cur.execute("SELECT to_regclass('public.blog_task')")
        if cur.fetchone()[0] is not None:
            raise RuntimeError("Refusing to run against an existing application database.")
    if args.worker_recovery or args.survivor_traffic:
        from worker_recovery import exercise, exercise_survivor
        db.close()
        (exercise_survivor if args.survivor_traffic else exercise)(fixture)
        return
    if args.mixed_faults:
        from mixed_faults import exercise
        try:
            exercise(args, fixture, db)
        finally:
            db.close()
        return

    calls, fixture_errors = Counter(), []
    lock = threading.Lock()

    class Endpoint(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["content-length"])))
            found = set(re.findall(r"CASE\d{3}", json.dumps(data["messages"], ensure_ascii=False)))
            if self.path != "/v1/chat/completions" or len(found) != 1:
                with lock:
                    fixture_errors.append({"path": self.path, "markers": sorted(found)})
                self.send_error(422)
                return
            marker = found.pop()
            content, kind = fixture(data, marker)
            with lock:
                calls[(marker, kind)] += 1
                invocation = calls[(marker, kind)]
            if args.provider_faults:
                if marker == "CASE002" and kind == "writer" and invocation == 2:
                    content += "\n\n这是第二版的待审稿正文。"
                if marker == "CASE000" and kind == "writer" and invocation == 1:
                    time.sleep(3.5)  # The real SDK read timeout is 2 seconds in this scenario.
                    self.close_connection = True
                    return
                if kind == "ReviewResult" and (
                    (marker == "CASE001" and invocation == 1) or (marker == "CASE002" and invocation == 2)
                ):
                    self.send_response(429)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Retry-After", "1")
                    self.end_headers()
                    self.wfile.write(
                        b'{"error":{"message":"private provider fixture marker","code":"rate_limit"}}'
                    )
                    return
            time.sleep(0.08)
            body = json.dumps(
                dict(
                    id="fixture",
                    object="chat.completion",
                    model="offline",
                    choices=[
                        dict(index=0, message=dict(role="assistant", content=content), finish_reason="stop")
                    ],
                )
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    endpoint = ThreadingHTTPServer(("127.0.0.1", 17871), Endpoint)
    threading.Thread(target=endpoint.serve_forever, daemon=True).start()
    ports, apps = [17870, 17872], []
    try:
        for port in ports:
            apps.append(
                subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "src.blog_agent.main:app",
                        "--port",
                        str(port),
                        "--no-access-log",
                        "--log-level",
                        "warning",
                    ]
                )
            )
        for port in ports:
            for _ in range(160):
                try:
                    if requests.get(f"http://127.0.0.1:{port}/api/v1/health", timeout=1).ok:
                        break
                except requests.ConnectionError:
                    pass
                time.sleep(0.15)
            else:
                raise TimeoutError("API startup failed")
        if args.provider_faults:
            from provider_faults import exercise

            exercise(ports, calls, lock, db)
            assert not fixture_errors
            return
        with db.cursor() as cur:
            cur.execute("""
              CREATE TABLE loadtest_events(id bigint, status text);
              CREATE FUNCTION loadtest_audit() RETURNS trigger LANGUAGE plpgsql AS $$
              BEGIN
                IF TG_OP='INSERT' OR OLD.status IS DISTINCT FROM NEW.status THEN
                  INSERT INTO loadtest_events VALUES(NEW.id,NEW.status);
                END IF;
                RETURN NEW;
              END; $$;
              CREATE TRIGGER loadtest_trace AFTER INSERT OR UPDATE ON generation_jobs
                FOR EACH ROW EXECUTE FUNCTION loadtest_audit();
            """)
        results, errors, task_ids = [], [], {}
        barrier = threading.Barrier(args.users, timeout=75)

        def author(i):
            marker = f"CASE{i:03d}"
            base = f"http://127.0.0.1:{ports[i%2]}/api/v1"
            with requests.Session() as client:

                def req(method, path, **kw):
                    res = client.request(method, base + path, timeout=10, **kw)
                    if not res.ok:
                        raise RuntimeError((path, res.status_code, res.text[:250]))
                    return res.json()

                email = marker.lower() + "@example.com"
                code = req("POST", "/auth/send-code", json={"email": email})["code"]
                password = secrets.token_hex(8) + "Q7"
                signup = req(
                    "POST",
                    "/auth/register",
                    json=dict(
                        email=email,
                        username=marker,
                        nickname=marker,
                        password=password,
                        confirm_password=password,
                        email_code=code,
                    ),
                )
                client.headers["Authorization"] = "Bearer " + signup["access_token"]
                task = req("POST", "/task", json={"topic": marker + " 验证主题"})["id"]
                root = f"/task/{task}"
                with lock:
                    task_ids[i] = task
                barrier.wait()
                start = time.monotonic()
                row = dict(
                    author=marker,
                    task=task,
                    api_port=ports[i % 2],
                    admission_seconds={},
                    stage_seconds={},
                    used=[],
                )

                def stage(stage_name, command, target, payload):
                    began = time.monotonic()
                    req("POST", root + "/" + command, json=payload)
                    row["admission_seconds"][stage_name] = time.monotonic() - began
                    while time.monotonic() - began < 150:
                        record = req("GET", root)
                        if record["status"] == "failed":
                            raise RuntimeError((stage_name, record.get("error")))
                        if record["status"] == target:
                            assert record["job"]["status"] == "succeeded" and record["job"]["attempt"] == 1
                            with client.get(base + root + "/stream", stream=True, timeout=6) as stream:
                                stream.raise_for_status()
                                line = next(
                                    line for line in stream.iter_lines() if line.startswith(b"data: ")
                                )
                                event = json.loads(line[6:])
                                assert event["status"] == record["status"] and event["job"] == record["job"]
                            assert set(re.findall(r"CASE\d{3}", json.dumps(record, ensure_ascii=False))) == {
                                marker
                            }
                            row["stage_seconds"][stage_name] = time.monotonic() - began
                            row["used"].append(req("GET", "/auth/quota")["used"])
                            return record
                        time.sleep(0.12)
                    raise TimeoutError(stage_name)

                titles = stage("title", "generate-titles", "title_generated", {})
                outline = stage(
                    "outline",
                    "submit-title-config",
                    "outline_generated",
                    dict(title=titles["titles"][0], article_style="note", need_image=False),
                )
                req(
                    "POST",
                    root + "/confirm-outline",
                    json=dict(outline=outline["outline"], word_count=260, level="general"),
                )
                stage("content", "generate-content", "completed", {})
                detail = req("GET", f"/blog/{task}")
                assert (
                    set(re.findall(r"CASE\d{3}", detail["formatted_content"])) == {marker}
                    and detail["review_result"]["passed"]
                )
                assert {x["id"] for x in req("GET", "/task")["items"]} == {task}
                other = task_ids[(i + 1) % args.users]
                assert client.get(f"{base}/task/{other}", timeout=5).status_code in (403, 404)
                assert row["used"] == [1, 2, 5] and req("GET", "/auth/quota")["active_jobs"] == 0
                row["e2e_seconds"] = time.monotonic() - start
                return row

        # Both counters come from the same PostgreSQL snapshot. Peaks between samples
        # are recovered separately below from transaction commit timestamps.
        sample_stop = threading.Event()
        sampled = {"count": 0, "queued_peak": 0, "running_peak": 0}

        def sample_queue():
            with psycopg2.connect(database_dsn) as reader:
                reader.autocommit = True
                with reader.cursor() as cur:
                    while not sample_stop.is_set():
                        cur.execute("""SELECT count(*) FILTER (WHERE status='queued'),
                                              count(*) FILTER (WHERE status='running')
                                       FROM generation_jobs""")
                        queued, running = cur.fetchone()
                        sampled["queued_peak"] = max(sampled["queued_peak"], queued)
                        sampled["running_peak"] = max(sampled["running_peak"], running)
                        sampled["count"] += 1
                        sample_stop.wait(0.1)

        sampler = threading.Thread(target=sample_queue, daemon=True)
        sampler.start()
        start_all = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(args.users) as pool:
            futures = {pool.submit(author, i): i for i in range(args.users)}
            for future in concurrent.futures.as_completed(futures):
                try:
                    row = future.result()
                    print("complete", row["author"], round(row["e2e_seconds"], 2), "s", flush=True)
                    results.append(row)
                except Exception as error:
                    errors.append([futures[future], repr(error)])
                    print("ERROR", errors[-1], flush=True)
        sample_stop.set()
        sampler.join(2)
        with db.cursor() as cur:
            cur.execute("""SELECT pg_xact_commit_timestamp(xmin),id,status FROM loadtest_events
                           ORDER BY pg_xact_commit_timestamp(xmin),id""")
            jobs, peak_queue, peak_running = {}, 0, 0
            from itertools import groupby

            for _, batch in groupby(cur.fetchall(), key=lambda item: item[0]):
                for _, job, status in batch:
                    jobs[job] = status
                peak_queue = max(peak_queue, sum(s == "queued" for s in jobs.values()))
                peak_running = max(peak_running, sum(s == "running" for s in jobs.values()))
            cur.execute(
                "SELECT status,stage,count(*),sum(attempt) FROM generation_jobs GROUP BY status,stage"
            )
            stage_jobs = cur.fetchall()
        stage_stats = {}
        if results:
            for stage_name in ["title", "outline", "content"]:
                stage_stats[stage_name] = {
                    field: summarize([r[field][stage_name] for r in results])
                    for field in ["admission_seconds", "stage_seconds"]
                }
        report = dict(
            users=args.users,
            api_instances=len(apps),
            worker_cap=args.workers,
            model_delay_ms=80,
            completed=len(results),
            errors=errors,
            fixture_errors=fixture_errors,
            queue_peak=peak_queue,
            running_peak=peak_running,
            sql_samples=sampled,
            jobs=[
                dict(status=status, stage=stage, count=count, attempts=attempts)
                for status, stage, count, attempts in stage_jobs
            ],
            stages=stage_stats,
            total_model_calls=sum(calls.values()),
            harness_seconds=round(time.monotonic() - start_all, 3),
            e2e_seconds=summarize([r["e2e_seconds"] for r in results]) if results else {},
            accounts=[
                dict(
                    author=r["author"],
                    task=r["task"],
                    api_port=r["api_port"],
                    used=r["used"],
                    model_calls=sum(n for (name, _), n in calls.items() if name == r["author"]),
                    e2e_seconds=round(r["e2e_seconds"], 3),
                )
                for r in sorted(results, key=lambda x: x["author"])
            ],
        )
        print(json.dumps(report, ensure_ascii=False), flush=True)
        assert not errors and not fixture_errors and len(results) == args.users
        assert sampled["count"] and 0 < sampled["running_peak"] <= peak_running
        assert (
            peak_queue
            and 0 < peak_running <= args.workers
            and all(
                s == "succeeded" and count == attempts == args.users for s, _, count, attempts in stage_jobs
            )
        )
        assert sum(calls.values()) == 13 * args.users
    finally:
        for app in apps:
            app.terminate()
        for app in apps:
            try:
                app.wait(timeout=12)
            except subprocess.TimeoutExpired:
                app.kill()
                app.wait()
        endpoint.shutdown()
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--users", type=int, choices=range(8, 13), default=10)
    parser.add_argument("--workers", type=int, choices=range(1, 6), default=3)
    parser.add_argument("--image", default="blog-agent-l-backendl:latest")
    scenarios = parser.add_mutually_exclusive_group()
    scenarios.add_argument("--mixed-faults", action="store_true",
                           help="Restart a replica during concurrent author workflows and provider faults")
    scenarios.add_argument(
        "--provider-faults",
        action="store_true",
        help="Check writer timeout, reviewer rate limit and private restoration after a failed rewrite",
    )
    scenarios.add_argument("--worker-recovery", action="store_true",
                           help="Interrupt owned test worker/API processes, verify recovery and quota")
    scenarios.add_argument("--survivor-traffic", action="store_true",
                           help="Check concurrent author traffic and bounded admission after one API exits")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args()
    if options.mixed_faults and options.workers < 2:
        parser.error("--mixed-faults requires at least two global execution slots")
    (run_case if options.inside else isolated_run)(options)
