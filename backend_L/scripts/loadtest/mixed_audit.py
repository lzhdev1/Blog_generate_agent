"""Read-only reconciliation for the disposable mixed-author benchmark."""
from collections import Counter
import hashlib
import json
import re


STAGE_COSTS = {"title": 1, "outline": 1, "content": 3, "revision": 1}


def _database(db):
    from psycopg2.extras import RealDictCursor

    # The harness supplies an idle psycopg2 connection. Use one consistent,
    # read-only snapshot and leave ownership of the connection with the caller.
    with db:
        with db.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            def rows(statement):
                cur.execute(statement)
                return [dict(row) for row in cur.fetchall()]

            return {
                "window": rows("SELECT floor(extract(epoch FROM now()) / 86400)::bigint AS n")[0]["n"],
                "jobs": rows("""
                    SELECT id, task_id, user_id, stage, status, attempt, max_attempts,
                           started_at IS NOT NULL AS started, finished_at IS NOT NULL AS finished,
                           token IS NOT NULL OR lease_until IS NOT NULL AS leased,
                           floor(extract(epoch FROM created_at) / 86400)::bigint AS charge_window
                    FROM generation_jobs ORDER BY id"""),
                "receipts": rows("SELECT task_id, key_hash, command_hash FROM generation_requests"),
                "reservations": rows("SELECT job_id FROM generation_reservations"),
                "usage": rows("""
                    SELECT scope, subject, "window", used FROM usage_window
                    WHERE scope IN ('user_generation', 'site_generation')"""),
                "tasks": rows("""
                    SELECT id, user_id, lower(status::text) AS status, topic, titles,
                           selected_title, title_research, outline, outline_research, content_research,
                           writing_thoughts, content, formatted_content
                    FROM blog_task WHERE is_demo IS NOT TRUE ORDER BY id"""),
            }


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _command_hash(action, data):
    if action == "submit-title-config":
        from src.blog_agent.schemas.task_schema import TitleAndConfigReq
        data = {"config": TitleAndConfigReq.model_validate(data).model_dump(exclude_unset=True)}
    else:
        data = None
    return _sha(json.dumps([action, data], sort_keys=True, separators=(",", ":")))


class Checks:
    def __init__(self):
        self.count = 0
        self.errors = []

    def equal(self, label, actual, expected):
        self.count += 1
        if actual != expected:
            self.errors.append({"check": label, "expected": expected, "actual": actual})


def _expected_calls(fault):
    calls = Counter({
        "research_plan": 3, "research_summary": 3, "TitleList": 1, "TitleScoreList": 1,
        "TitleReviewResult": 1, "outliner": 1, "OutlineReviewResult": 1,
        "writer": 1, "ReviewResult": 1,
    })
    if fault is not None:
        # The failed first content stage reached the writer in all three fault
        # cases. Only the reviewer-429 scenario reached the review request.
        calls.update(["research_plan", "research_summary", "writer"])
        if fault == "reviewer_429":
            calls["ReviewResult"] += 1
    return dict(calls)


def _markers(data):
    return sorted(set(re.findall(r"CASE\d+", json.dumps(data, ensure_ascii=False))))


def _http_account(account, peer, origin, row, receipts, checks):
    import requests

    uid, task_id, marker = account["user_id"], account["task"], account["marker"]
    path = f"/task/{task_id}"
    observations = {"requests": 0, "receipt_echoes": 0}
    with requests.Session() as client:
        client.trust_env = False
        client.headers["Authorization"] = "Bearer " + account["token"]

        def get(suffix, *, key=None, denied=False):
            observations["requests"] += 1
            label = "HTTP " + suffix
            try:
                with client.get(origin + suffix, headers={"Idempotency-Key": key} if key else {},
                                timeout=(3, 8), allow_redirects=False, stream=denied) as response:
                    if denied:
                        checks.equal(label + " rejects other author", response.status_code in (403, 404), True)
                        return response.status_code
                    checks.equal(label + " status", response.status_code, 200)
                    return response.json() if response.status_code == 200 else {}
            except (requests.RequestException, ValueError) as exc:
                checks.equal(label + " transport", type(exc).__name__, "OK")
                return None if denied else {}

        checks.equal("authenticated user", get("/auth/me").get("id"), uid)
        quota = get("/auth/quota")
        checks.equal("published stage costs", quota.get("stage_costs"), STAGE_COSTS)
        checks.equal("active jobs on quota endpoint", quota.get("active_jobs"), 0)
        observations["used"] = quota.get("used")
        observations["remaining"] = quota.get("remaining")
        observations["limit"] = quota.get("daily_limit")
        if all(isinstance(observations[k], int) for k in ("limit", "used")):
            checks.equal("published remaining", observations["remaining"], observations["limit"] - observations["used"])
        else:
            checks.equal("quota numeric fields present", False, True)
        items = get("/my/articles?tab=created&limit=200")
        checks.equal("own library total", items.get("total"), 1)
        checks.equal("own library task IDs", [item.get("task_id") for item in items.get("items", [])], [task_id])
        checks.equal("library marker", _markers(items), [marker])
        own = get(path)
        checks.equal("HTTP task ID", own.get("id"), task_id)
        checks.equal("HTTP task owner", own.get("user_id"), uid)
        checks.equal("HTTP final state", own.get("status"), "completed")
        checks.equal("HTTP task markers", _markers(own), [marker])
        checks.equal("HTTP content matches stored manuscript", bool(row and own.get("formatted_content") and
                     own["formatted_content"] == row.get("formatted_content")), True)
        article = get(f"/blog/{task_id}")
        checks.equal("reader final manuscript", bool(own.get("formatted_content")) and
                     article.get("formatted_content") == own["formatted_content"], True)
        for index, command in enumerate(receipts, start=1):
            response = get(path, key=command["key"])
            echoed = response.get("accepted_request_key") == command["key"]
            checks.equal(f"receipt {index} acknowledged by API", echoed, True)
            observations["receipt_echoes"] += int(echoed)
        if peer is not None:
            observations["peer_task"] = peer["task"]
            observations["peer_detail_status"] = get(f"/task/{peer['task']}", denied=True)
            observations["peer_stream_status"] = get(f"/task/{peer['task']}/stream", denied=True)
    return observations


def _account(account, peer, state, counters, origin):
    checks = Checks()
    uid, task_id, marker, fault = (account[k] for k in ("user_id", "task", "marker", "fault"))
    checks.equal("known fault", fault in (None, "writer_timeout", "reviewer_429", "api_crash"), True)
    expected_stages = ["title", "outline", "content"] + (["content"] if fault else [])
    expected_status = ["succeeded", "succeeded"] + (["failed"] if fault else []) + ["succeeded"]
    expected_actions = ["generate-titles", "submit-title-config", "generate-content"] + (["generate-content"] if fault else [])
    charges = [1, 2, 5, 5, 8] if fault else [1, 2, 5]
    checks.equal("HTTP quota during original/replay/retry", account["used"], charges)
    checks.equal("manifest stage count", account["expected_jobs"], len(expected_stages))
    author_rows = [row for row in state["tasks"] if row["user_id"] == uid]
    checks.equal("database author task IDs", [row["id"] for row in author_rows], [task_id])
    row = next((r for r in author_rows if r["id"] == task_id), {})
    checks.equal("database final state", row.get("status"), "completed")
    for field in ("topic", "titles", "selected_title", "outline", "content", "formatted_content"):
        checks.equal("database " + field + " marker", _markers(row.get(field)), [marker])
    checks.equal("all stored manuscript markers", _markers(row), [marker])
    jobs = [j for j in state["jobs"] if j["task_id"] == task_id]
    checks.equal("stage sequence", [j["stage"] for j in jobs], expected_stages)
    checks.equal("terminal job sequence", [j["status"] for j in jobs], expected_status)
    billed = 0
    job_report = []
    for job in jobs:
        label = f"job {job['id']}"
        checks.equal(label + " owner", job["user_id"], uid)
        checks.equal(label + " attempts", job["attempt"], 1)
        checks.equal(label + " completed claim", job["started"] and job["finished"] and not job["leased"], True)
        units = STAGE_COSTS.get(job["stage"], 0) if job["started"] else 0
        if job["charge_window"] == state["window"]:
            billed += units
        job_report.append({k: job[k] for k in ("id", "stage", "status", "attempt", "started")} | {"units": units})
    expected_receipts = account["accepted_requests"]
    checks.equal("accepted commands", [cmd["action"] for cmd in expected_receipts], expected_actions)
    actual = {r["key_hash"]: r["command_hash"] for r in state["receipts"] if r["task_id"] == task_id}
    expected = {_sha(cmd["key"]): _command_hash(cmd["action"], cmd.get("data")) for cmd in expected_receipts}
    checks.equal("distinct keys for independent admissions", len(expected), len(expected_stages))
    checks.equal("receipt key set", set(actual) == set(expected), True)
    matching = sum(actual.get(key) == digest for key, digest in expected.items())
    checks.equal("matching receipt commands and payloads", matching, len(expected_stages))
    usage = sum(r["used"] for r in state["usage"] if r["scope"] == "user_generation" and
                r["subject"] == str(uid) and r["window"] == state["window"])
    checks.equal("cost of started stages", billed, charges[-1])
    checks.equal("persisted author usage", usage, billed)
    expected_calls = _expected_calls(fault)
    actual_calls = counters.get(marker, {})
    checks.equal("model calls per operation", actual_calls, expected_calls)
    replay_delta = None
    if "replay_before" in account and "replay_after" in account:
        before, after = account["replay_before"], account["replay_after"]
        checks.equal("per-operation counts unchanged by same-key replay", after, before)
        replay_delta = sum(after.values()) - sum(before.values())
    http = _http_account(account, peer, origin, row, expected_receipts, checks)
    checks.equal("HTTP and database credits used", http["used"], usage)
    return {
        "author": marker, "user_id": uid, "task_id": task_id, "fault": fault,
        "jobs": job_report, "expected_units": charges[-1], "job_units": billed, "db_used": usage,
        "http": http, "used_history": account["used"], "receipt_count": len(actual),
        "verified_commands": matching, "expected_model_calls": sum(expected_calls.values()),
        "model_calls": sum(actual_calls.values()), "model_calls_by_kind": actual_calls,
        "model_calls_added_by_replay": replay_delta,
        "checks": checks.count, "errors": checks.errors, "passed": not checks.errors,
    }


def audit(manifest, model_counters, db, origin):
    """Reconcile all authors after the run drains. Caller exits nonzero on passed=False.

    The manifest and HTTP tokens remain in memory. The returned report contains
    no credentials or reusable idempotency keys. No POST or SQL mutation is made.
    """
    state = _database(db)
    checks = Checks()
    authors = sorted(manifest, key=lambda item: item["marker"])
    markers = [author["marker"] for author in authors]
    checks.equal("at least one author", bool(authors), True)
    checks.equal("distinct author markers", len(set(markers)), len(authors))
    checks.equal("distinct author identities", len({a["user_id"] for a in authors}), len(authors))
    checks.equal("distinct task IDs", len({a["task"] for a in authors}), len(authors))
    checks.equal("all model markers", sorted(model_counters), sorted(markers))
    checks.equal("all database task IDs", [r["id"] for r in state["tasks"]], sorted(a["task"] for a in authors))
    accounts = []
    for i, author in enumerate(authors):
        peer = authors[(i + 1) % len(authors)] if len(authors) > 1 else None
        accounts.append(_account(author, peer, state, model_counters, origin))
    jobs = state["jobs"]
    queued = sum(job["status"] == "queued" for job in jobs)
    running = sum(job["status"] == "running" for job in jobs)
    reservations = len(state["reservations"])
    checks.equal("remaining queued jobs", queued, 0)
    checks.equal("remaining running jobs", running, 0)
    checks.equal("remaining quota reservations", reservations, 0)
    expected_jobs = sum(a["expected_jobs"] for a in authors)
    checks.equal("all job rows", len(jobs), expected_jobs)
    checks.equal("all receipt rows", len(state["receipts"]), expected_jobs)
    today = [r for r in state["usage"] if r["window"] == state["window"]]
    site_units = sum(r["used"] for r in today if r["scope"] == "site_generation" and r["subject"] == "all")
    user_units = sum(r["used"] for r in today if r["scope"] == "user_generation")
    expected_units = sum(a["expected_units"] for a in accounts)
    checks.equal("sum of all author counters", user_units, expected_units)
    checks.equal("site daily usage", site_units, expected_units)
    return {
        "passed": not checks.errors and all(a["passed"] for a in accounts),
        "checks": checks.count + sum(a["checks"] for a in accounts),
        "error_count": len(checks.errors) + sum(len(a["errors"]) for a in accounts),
        "errors": checks.errors, "failed_authors": [a["author"] for a in accounts if not a["passed"]],
        "utc_window": state["window"], "users": len(authors), "tasks": len(state["tasks"]),
        "jobs": len(jobs), "receipts": len(state["receipts"]), "queued": queued, "running": running,
        "reservations": reservations, "expected_units": expected_units, "user_units": user_units,
        "site_units": site_units, "model_calls": sum(sum(counts.values()) for counts in model_counters.values()),
        "accounts": accounts,
    }
