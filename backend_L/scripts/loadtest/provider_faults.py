"""Fault scenario for isolated_http.py --provider-faults (uses its disposable DB and mock)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import secrets
from time import monotonic, sleep


def exercise(ports, calls, lock, db):
    import requests

    tokens = {}

    def author(index):
        base = f"http://127.0.0.1:{ports[index%len(ports)]}/api/v1"
        marker = f"CASE{index:03d}"
        fault = ["writer_read_timeout", "reviewer_http_429", "rewrite_429_restore"][index]
        expected = "模型服务响应超时" if index == 0 else "模型服务当前限流"
        started = monotonic()

        def count_calls():
            with lock:
                return {kind: count for (name, kind), count in calls.items() if name == marker}

        with requests.Session() as client:

            def request(method, path, payload=None, key=None):
                headers = {"Idempotency-Key": key} if key else {}
                response = client.request(method, base + path, json=payload, headers=headers, timeout=8)
                if not response.ok:
                    raise AssertionError((fault, path, response.status_code, response.text[:256]))
                return response.json()

            def wait_for(status):
                previous = []
                until = monotonic() + 60
                while monotonic() < until:
                    record = request("GET", path)
                    if not previous or previous[-1] != record["status"]:
                        previous.append(record["status"])
                    if record["status"] == status:
                        return record, previous
                    if record["status"] == "failed" and status != "failed":
                        raise AssertionError((fault, record["error"], previous))
                    sleep(0.1)
                raise TimeoutError((fault, status, previous))

            def used():
                return request("GET", "/auth/quota")["used"]

            email = marker.lower() + "@example.com"
            code = request("POST", "/auth/send-code", {"email": email})["code"]
            password = "Q7" + secrets.token_hex(12)
            signup = request(
                "POST",
                "/auth/register",
                dict(
                    email=email,
                    username=marker,
                    nickname=marker,
                    password=password,
                    confirm_password=password,
                    email_code=code,
                ),
            )
            client.headers.update({"Authorization": "Bearer " + signup["access_token"]})
            with lock:
                tokens[index] = signup["access_token"]
            task_id = request("POST", "/task", {"topic": marker + " 验证主题"})["id"]
            path = f"/task/{task_id}"
            request("POST", path + "/generate-titles", {}, secrets.token_hex(16))
            titles, _ = wait_for("title_generated")
            request(
                "POST",
                path + "/submit-title-config",
                dict(
                    title=titles["titles"][0],
                    article_style="note",
                    need_image=False,
                    extra_requirements="保留署名",
                ),
                secrets.token_hex(16),
            )
            outline, _ = wait_for("outline_generated")
            confirmed = request(
                "POST",
                path + "/confirm-outline",
                dict(
                    outline=outline["outline"],
                    word_count=260,
                    level="general",
                    content_extra_requirements="强调核对步骤",
                ),
            )
            fields = (
                "selected_title",
                "outline",
                "outline_confirmed",
                "article_style",
                "need_image",
                "level",
                "extra_requirements",
                "content_extra_requirements",
                "word_count",
                "titles",
                "title_research",
                "outline_research",
            )
            config = {k: confirmed[k] for k in fields}
            if index == 2:
                request("POST", path + "/generate-content", {}, secrets.token_hex(16))
                original, _ = wait_for("completed")
                assert original["review_result"]["passed"] and used() == 5
                published = request(
                    "PUT", path + "/visibility", dict(is_public=True, allow_download=True, download_price=3,
                                                       expected_revision=original["revision"])
                )
                assert published["is_public"] and published["allow_download"]
            used_before = used()
            baseline = sum(count_calls().values())
            key = secrets.token_hex(16)
            before_fault = monotonic()
            admission = request("POST", path + "/generate-content", {}, key)
            failed, states = wait_for("failed")
            failure_seconds = monotonic() - before_fault
            assert failed["job"]["status"] == "failed" and failed["job"]["attempt"] == 1
            assert not failed.get("formatted_content") and not failed.get("is_public")
            assert config == {k: failed[k] for k in fields} and failed["outline_confirmed"]
            assert expected in failed["error"] and "private provider" not in failed["error"], failed["error"]
            assert marker in failed["content_research"]
            if index == 2:
                assert failed["can_restore_previous"] and failed["content"] != original["content"]
                assert "第二版" in failed["content"] and "第二版" not in original["content"]
                with lock:
                    other_headers = {"Authorization": "Bearer " + tokens[0]}
                wrong_restore = requests.post(
                    base + path + "/restore-previous", headers=other_headers, timeout=5
                )
                assert wrong_restore.status_code in (403, 404)
                before_restore_calls = count_calls()
                before_restore_used = used()
                began_restore = monotonic()
                restored = request("POST", path + "/restore-previous", {})
                elapsed_restore = monotonic() - began_restore
                manuscript_fields = (
                    *fields,
                    "content",
                    "writing_thoughts",
                    "content_research",
                    "formatted_content",
                    "review_result",
                    "review_feedback",
                    "image_prompts",
                    "image_urls",
                    "title_scores",
                )
                assert all(restored[k] == original[k] for k in manuscript_fields)
                assert restored["status"] == "completed" and not restored["error"] and not restored["job"]
                assert (
                    not restored["can_restore_previous"]
                    and not restored["is_public"]
                    and not restored["allow_download"]
                )
                assert restored["download_price"] == 0
                owner_detail = request("GET", f"/blog/{task_id}")
                assert (
                    owner_detail["formatted_content"] == original["formatted_content"]
                    and owner_detail["review_result"] == original["review_result"]
                )
                assert not request("GET", path)["can_restore_previous"]
                with client.get(base + path + "/stream", stream=True, timeout=5) as stream:
                    stream.raise_for_status()
                    line = next(line for line in stream.iter_lines() if line.startswith(b"data: "))
                    event = json.loads(line[6:])
                    assert event["status"] == "completed" and not event["job"]
                other_statuses = {
                    endpoint: requests.get(base + endpoint, headers=other_headers, timeout=5).status_code
                    for endpoint in (path, f"/blog/{task_id}", f"/articles/{task_id}")
                }
                assert all(status in (403, 404) for status in other_statuses.values())
                after_restore_used = used()
                after_restore_calls = count_calls()
                assert after_restore_used == before_restore_used and after_restore_calls == before_restore_calls
                replay = request("POST", path + "/generate-content", {}, key)
                assert replay["status"] == "completed" and replay["content"] == original["content"]
                assert (
                    used() == before_restore_used == 8 and request("GET", "/auth/quota")["active_jobs"] == 0
                )
                assert count_calls() == before_restore_calls and sum(before_restore_calls.values()) == 17
                return dict(
                    case=fault,
                    task=task_id,
                    used=[used_before, before_restore_used, after_restore_used, used()],
                    failed_rewrite_error=failed["error"],
                    distinct_failed_draft=True,
                    original_public=True,
                    restored_private=True,
                    original_fields_verified=len(manuscript_fields),
                    after_restore_state=restored["status"],
                    after_replay_state=replay["status"],
                    other_restore_http=wrong_restore.status_code,
                    other_read_http=other_statuses,
                    author_detail_read=True,
                    sse_restored=True,
                    model_calls_before_restore=sum(before_restore_calls.values()),
                    model_calls_after_restore=sum(after_restore_calls.values()),
                    model_calls_after_replay=sum(count_calls().values()),
                    restoration_seconds=round(elapsed_restore, 3),
                    e2e_seconds=round(monotonic() - started, 2),
                )
            if index == 1:
                assert marker in failed["content"] and marker in failed["writing_thoughts"]
                assert not failed.get("review_result")
            else:
                assert not failed.get("content")
            used_after_failure = used()
            failed_calls = count_calls()
            assert failed_calls["writer"] == 1
            assert failed_calls.get("ReviewResult", 0) == index
            replay = request("POST", path + "/generate-content", {}, key)
            assert replay["status"] == "failed" and replay["job"] == failed["job"]
            assert replay["error"] == failed["error"]
            assert count_calls() == failed_calls
            used_after_replay = used()
            retry = request("POST", path + "/generate-content", {}, secrets.token_hex(16))
            completed, _ = wait_for("completed")
            assert completed["job"]["status"] == "succeeded" and completed["job"]["attempt"] == 1
            assert config == {k: completed[k] for k in fields}
            article = request("GET", f"/blog/{task_id}")
            assert (
                marker in article["formatted_content"]
                and article["review_result"]["passed"]
                and not completed["error"]
            )
            quota_sequence = [used_before, used_after_failure, used_after_replay, used()]
            assert quota_sequence == [2, 5, 5, 8]
            assert request("GET", "/auth/quota")["active_jobs"] == 0
            final_calls = count_calls()
            assert final_calls["writer"] == 2 and sum(final_calls.values()) - sum(failed_calls.values()) == 4
            return dict(
                case=fault,
                task=task_id,
                used=quota_sequence,
                submission=admission["status"],
                failed_job=failed["job"]["status"],
                error=failed["error"],
                replay=replay["status"],
                retry_submission=retry["status"],
                recovered=completed["status"],
                config_retained=True,
                failed_research_saved=bool(failed.get("content_research")),
                failed_draft_saved=bool(failed.get("content")),
                failed_plan_saved=bool(failed.get("writing_thoughts")),
                failed_has_final=bool(failed.get("formatted_content")),
                before_model_calls=baseline,
                failed_content_calls=sum(failed_calls.values()) - baseline,
                replay_extra_model_calls=0,
                retry_content_calls=sum(final_calls.values()) - sum(failed_calls.values()),
                exact_model_calls=final_calls,
                states=states,
                failure_seconds=round(failure_seconds, 2),
                e2e_seconds=round(monotonic() - started, 2),
            )

    began = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with ThreadPoolExecutor(3) as pool:
        results = list(pool.map(author, range(3)))
    with db.cursor() as cur:
        cur.execute(
            "SELECT task_id,status,count(*),sum(attempt) FROM generation_jobs WHERE stage='content' GROUP BY task_id,status ORDER BY task_id,status"
        )
        jobs = cur.fetchall()
    assert len(jobs) == 6 and all(count == tries == 1 for _, _, count, tries in jobs)
    print(
        json.dumps(
            dict(
                started_utc=began,
                finished_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                scenarios=results,
                content_jobs=jobs,
                sdk_retries=0,
                provider_timeout_s=2,
            ),
            ensure_ascii=False,
        ),
        flush=True,
    )
