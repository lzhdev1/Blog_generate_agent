# -*- coding: utf-8 -*-
"""全链路 HTTP 计时脚本（不含人工操作等待）

流程：
  注册/登录 -> 创建任务 -> 生成标题（调研+生成+质量门）
  -> 选标题并提交配置 -> 生成大纲（调研+生成+质量门）
  -> 确认大纲 -> 生成正文（调研+写作+审稿打回+配图+排版）

计时口径：每个阶段从对应 POST 发起，到轮询看到该阶段终态为止；
人工介入点由脚本立即自动提交，因此统计的是纯机器执行时间。

输出：同目录下 bench_full_chain_<时间戳>.log / .json
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8001/api/v1"
TOPIC = "AI Agent 在企业中的应用趋势"
WORD_COUNT = 1200
LEVEL = "advanced"
NEED_IMAGE = True
IMAGE_SOURCE = "api"

STAGE_TIMEOUT = {
    "title": 1500,
    "outline": 1500,
    "content": 2400,
}

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
STAMP = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_PATH = os.path.join(OUT_DIR, f"bench_full_chain_{STAMP}.log")
RESULT_PATH = os.path.join(OUT_DIR, f"bench_full_chain_{STAMP}.json")


def log(msg):
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def http(method, path, body=None, token=None, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw
        return e.code, parsed


def api(method, path, body=None, token=None, timeout=60, expect=(200,)):
    status, obj = http(method, path, body=body, token=token, timeout=timeout)
    if status not in expect:
        raise RuntimeError(f"{method} {path} -> HTTP {status}: {obj}")
    return obj


def wait_task(task_id, token, targets, stage_name, max_wait):
    """轮询任务直到目标状态；返回 (task, 用时, 状态时间线)"""
    t0 = time.monotonic()
    last_sig = None
    timeline = []
    while True:
        elapsed = time.monotonic() - t0
        if elapsed > max_wait:
            raise TimeoutError(f"{stage_name} 超过 {max_wait}s 未完成")
        status, obj = http("GET", f"/task/{task_id}", token=token, timeout=30)
        if status != 200:
            raise RuntimeError(f"查询任务失败 HTTP {status}: {obj}")
        sig = (obj.get("status"), obj.get("progress"))
        if sig != last_sig:
            timeline.append({"elapsed_s": round(elapsed, 1), "status": sig[0], "progress": sig[1]})
            log(f"  [{stage_name} +{elapsed:6.1f}s] status={sig[0]} | {sig[1]}")
            last_sig = sig
        if obj.get("status") in targets:
            return obj, elapsed, timeline
        if obj.get("status") == "failed":
            raise RuntimeError(f"{stage_name}失败: {obj.get('error')}")
        time.sleep(1)


def extract_cost(timeline):
    """从 progress 文本中提取 生成/审核 耗时（若埋点存在）"""
    out = []
    for item in timeline:
        text = item.get("progress") or ""
        m = re.search(r"生成耗时\s*([\d.]+)s", text)
        if m:
            out.append({"elapsed_s": item["elapsed_s"], "gen_cost_s": float(m.group(1))})
        m = re.search(r"生成\s*([\d.]+)s\s*\+\s*审核\s*([\d.]+)s", text)
        if m:
            out.append({
                "elapsed_s": item["elapsed_s"],
                "gen_cost_s": float(m.group(1)),
                "gate_cost_s": float(m.group(2)),
            })
    return out


def main():
    log(f"开始全链路计时 | topic={TOPIC} | word_count={WORD_COUNT} | need_image={NEED_IMAGE}({IMAGE_SOURCE})")
    log(f"日志: {LOG_PATH}")

    # ---------- 0. 注册 / 登录 ----------
    ts = datetime.datetime.now().strftime("%m%d%H%M%S")
    username = "bench" + ts
    email = f"bench{ts}@example.com"
    password = "Bench2026a!"
    nickname = "Bench跑测"

    status, obj = http("POST", "/auth/register", {
        "nickname": nickname,
        "email": email,
        "email_code": "888888",
        "username": username,
        "password": password,
        "confirm_password": password,
    })
    if status == 200:
        token = obj["access_token"]
        log(f"注册成功: {username}")
    else:
        log(f"注册失败({status})，尝试登录: {obj}")
        login = api("POST", "/auth/login", {"account": username, "password": password})
        token = login["access_token"]
        log(f"登录成功: {username}")

    # ---------- 1. 标题阶段 ----------
    task = api("POST", "/task", {"topic": TOPIC}, token=token)
    task_id = task["id"]
    log(f"创建任务 task_id={task_id}, status={task['status']}")

    t_title = time.monotonic()
    api("POST", f"/task/{task_id}/generate-titles", token=token)
    log("[标题阶段] 已触发 generate-titles")
    task, title_s, title_tl = wait_task(
        task_id, token, {"title_generated"}, "标题阶段", STAGE_TIMEOUT["title"]
    )
    title_s = time.monotonic() - t_title
    titles = task.get("titles") or []
    if not titles:
        raise RuntimeError("标题阶段完成但没有返回标题")
    log(f"[标题阶段] 完成，用时 {title_s:.1f}s，产出 {len(titles)} 个标题")

    # ---------- 2. 大纲阶段 ----------
    selected_title = titles[0]
    t_outline = time.monotonic()
    api("POST", f"/task/{task_id}/submit-title-config", {
        "title": selected_title,
        "need_image": NEED_IMAGE,
        "article_style": "technical",
        "article_style_custom": None,
        "extra_requirements": None,
    }, token=token)
    log(f"[大纲阶段] 已选标题: {selected_title}，已触发 submit-title-config")
    task, _, outline_tl = wait_task(
        task_id, token, {"outline_generated"}, "大纲阶段", STAGE_TIMEOUT["outline"]
    )
    outline_s = time.monotonic() - t_outline
    outline = task.get("outline") or ""
    log(f"[大纲阶段] 完成，用时 {outline_s:.1f}s，大纲 {len(outline)} 字符")

    # ---------- 3. 正文阶段 ----------
    api("POST", f"/task/{task_id}/confirm-outline", {
        "outline": outline,
        "word_count": WORD_COUNT,
        "level": LEVEL,
        "content_extra_requirements": None,
        "image_source": IMAGE_SOURCE,
    }, token=token)
    t_content = time.monotonic()
    api("POST", f"/task/{task_id}/generate-content", token=token)
    log("[正文阶段] 已确认大纲并触发 generate-content")
    task, _, content_tl = wait_task(
        task_id, token, {"completed"}, "正文阶段", STAGE_TIMEOUT["content"]
    )
    content_s = time.monotonic() - t_content
    log(f"[正文阶段] 完成，用时 {content_s:.1f}s")

    # ---------- 4. 结果汇总 ----------
    blog = api("GET", f"/blog/{task_id}", token=token)
    final_content = blog.get("formatted_content") or blog.get("content") or ""
    chars = blog.get("word_count")
    if chars is None:
        chars = len(re.sub(r"\s", "", final_content))
    image_urls = blog.get("image_urls") or []
    review = blog.get("review_result") or {}
    total = title_s + outline_s + content_s

    result = {
        "topic": TOPIC,
        "task_id": task_id,
        "timestamp": STAMP,
        "config": {
            "word_count": WORD_COUNT,
            "level": LEVEL,
            "need_image": NEED_IMAGE,
            "image_source": IMAGE_SOURCE,
            "max_review_rounds": 2,
        },
        "stage_seconds": {
            "title": round(title_s, 1),
            "outline": round(outline_s, 1),
            "content": round(content_s, 1),
            "total_machine": round(total, 1),
        },
        "threshold_480s": {
            "limit": 480,
            "total": round(total, 1),
            "passed": total <= 480,
            "over_by": round(max(0, total - 480), 1),
        },
        "final_status": task.get("status"),
        "output": {
            "title_count": len(titles),
            "selected_title": selected_title,
            "outline_chars": len(outline),
            "content_chars_no_space": chars,
            "image_count": len(image_urls),
            "review_score": review.get("score"),
            "review_passed": review.get("passed"),
        },
        "cost_breakdown_from_progress": {
            "title": extract_cost(title_tl),
            "outline": extract_cost(outline_tl),
            "content": extract_cost(content_tl),
        },
        "timeline": {
            "title": title_tl,
            "outline": outline_tl,
            "content": content_tl,
        },
        "log_path": LOG_PATH,
    }

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    log("=" * 60)
    log(f"标题阶段: {title_s:.1f}s")
    log(f"大纲阶段: {outline_s:.1f}s")
    log(f"正文阶段: {content_s:.1f}s")
    log(f"机器总耗时: {total:.1f}s ({total/60:.2f} min)")
    log(f"8 分钟阈值: {'通过' if total <= 480 else '超出 ' + str(round(total-480,1)) + 's'}")
    log(f"结果文件: {RESULT_PATH}")
    log("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log(f"BENCH_FAILED: {type(e).__name__}: {e}")
        raise
