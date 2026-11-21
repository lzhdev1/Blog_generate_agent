"""Atomic fixed-window budgets shared by every web and worker process."""
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network

from fastapi import HTTPException, Request
from sqlalchemy import func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from config.model_limits import limits as model_limits
from config.settings import settings
from src.blog_agent.db.access_models import EmailChallenge, WindowCounter

DAY = 86400
STAGE_COSTS = {"title": 1, "outline": 1, "content": 3, "revision": 1}


def insert_for(db: Session, model):
    return (sqlite_insert if db.get_bind().dialect.name == "sqlite" else pg_insert)(model)


def _exhausted(code, message, remaining_seconds, status):
    return HTTPException(status, detail={"code": code, "message": message},
                         headers={"Retry-After": str(remaining_seconds)})


def _consume(db, scope, subject, cost, limit, seconds, code, message, now, status=429):
    window = now // seconds
    end = (window + 1) * seconds
    if cost > limit:
        raise _exhausted(code, message, end - now, status)
    stmt = insert_for(db, WindowCounter).values(scope=scope, subject=subject,
                                              window=window, used=cost, expires=end)
    stmt = stmt.on_conflict_do_update(
        index_elements=["scope", "subject", "window"],
        set_={"used": WindowCounter.used + cost},
        where=WindowCounter.used <= limit - cost,
    ).returning(WindowCounter.used)
    if db.execute(stmt).scalar_one_or_none() is None:
        raise _exhausted(code, message, end - now, status)


def _generation_rules(db, task):
    if not model_limits.enabled:
        raise HTTPException(503, detail={"code": "generation_paused", "message": "生成服务已暂停，稿件仍可继续查看。"})
    if settings.app_env == "production":
        from src.blog_agent.db.models import User
        if not db.scalar(select(User.email_verified).where(User.id == task.user_id)):
            raise HTTPException(403, detail={"code": "email_unverified", "message": "正式环境需要已验证邮箱的账号才能生成文章。"})
    return (
        ("site_generation", "all", settings.site_daily_units, "site_daily_limit", "今日全站生成额度已用完，请在额度重置后重试。", 503),
        ("user_generation", str(task.user_id), settings.free_daily_units, "daily_quota", "今日剩余额度不足以启动这个阶段，已保存当前稿件。", 429),
    )


def check_generation_quota(db, task, stage):
    """Read-only rejection under contention; a later admission still reserves atomically."""
    rules = _generation_rules(db, task)
    now = int(time.time())
    window = now // DAY
    counters = db.execute(select(WindowCounter.scope, WindowCounter.used).where(
        WindowCounter.window == window,
        tuple_(WindowCounter.scope, WindowCounter.subject).in_([(scope, subject) for scope, subject, *_ in rules]),
    )).all()
    used = dict(counters)
    for scope, _, limit, code, message, status in rules:
        if used.get(scope, 0) + STAGE_COSTS[stage] > limit:
            raise _exhausted(code, message, (window + 1) * DAY - now, status)


def reserve_generation(db, task, stage):
    now = int(time.time())
    cost = STAGE_COSTS[stage]
    for scope, subject, limit, code, message, status in _generation_rules(db, task):
        _consume(db, scope, subject, cost, limit, DAY, code, message, now, status)
    return now // DAY, cost


def refund_generation(db, user_id, window, units):
    # Match reservation's site-then-account lock order. Old, pruned windows
    # require no update and must never produce credit in the current window.
    for scope, subject in (("site_generation", "all"), ("user_generation", str(user_id))):
        db.execute(update(WindowCounter).where(
            WindowCounter.scope == scope, WindowCounter.subject == subject,
            WindowCounter.window == window, WindowCounter.used >= units,
        ).values(used=WindowCounter.used - units))


def reserve_draft(db, user_id):
    _consume(db, "drafts", str(user_id), 1, settings.free_daily_drafts, DAY,
             "draft_limit", "今日新建稿件数量已达上限。", int(time.time()))


def quota_for(db, user_id):
    from src.blog_agent.db.job_models import GenerationJob
    from src.blog_agent.service.job_queue import ACTIVE

    now = int(time.time())
    window = now // DAY
    daily = select(WindowCounter.used).where(
        WindowCounter.scope == "user_generation", WindowCounter.subject == str(user_id),
        WindowCounter.window == window,
    ).scalar_subquery()
    # Charging and admission commit together. Report them from one statement snapshot.
    used, active = db.execute(
        select(func.coalesce(daily, 0), func.count()).select_from(GenerationJob)
        .where(GenerationJob.user_id == user_id, GenerationJob.status.in_(ACTIVE))
    ).one()
    return {
        "plan": "free", "daily_limit": settings.free_daily_units, "used": used,
        "remaining": max(0, settings.free_daily_units - used),
        "resets_at": datetime.fromtimestamp((window + 1) * DAY, timezone.utc),
        "active_jobs": active, "max_active_jobs": settings.free_max_active_jobs,
        "stage_costs": STAGE_COSTS,
    }


def _private_key(value):
    return hmac.new(settings.jwt_secret.encode(), value.strip().lower().encode(), hashlib.sha256).hexdigest()


def _client(request: Request):
    # ASGI's peer is set by Uvicorn using its trusted-proxy allowlist. Never
    # parse an arbitrary X-Forwarded-For header at the application boundary.
    host = request.client.host if request.client else "unknown"
    try:
        address = ip_address(host)
        return str(ip_network(f"{address}/64", strict=False)) if address.version == 6 else str(address)
    except ValueError:
        return host


def limit_auth(db, request, action, identity):
    """Persist attempts before password hashing, SMTP or registration validation."""
    rules = {
        "login": [(settings.auth_login_per_ip, 900), (10, 900)],
        "register": [(settings.auth_register_per_ip, 3600), (6, 900)],
        "send": [(settings.auth_send_per_ip, 3600), (1, 60)],
        "password": [(30, 900), (6, 900)],
    }
    now = int(time.time())
    for label, key, (limit, duration) in zip(("ip", "identity"), (_client(request), identity), rules[action]):
        _consume(db, f"{action}_{label}", _private_key(key), 1, limit, duration,
                 "rate_limited", "操作过于频繁，请稍后重试。", now)
    if action == "send":
        _consume(db, "mail_global", "all", 1, 200, 3600, "mail_limit", "邮件发送繁忙，请稍后再试。", now)
    # Bound maintenance work and avoid storing expired IP/account counters indefinitely.
    if secrets.randbelow(64) == 0:
        expired = select(WindowCounter.scope, WindowCounter.subject, WindowCounter.window).where(
            WindowCounter.expires < now - DAY).limit(256)
        key = tuple_(WindowCounter.scope, WindowCounter.subject, WindowCounter.window)
        db.query(WindowCounter).filter(key.in_(expired)).delete(synchronize_session=False)
        stale = select(EmailChallenge.email).where(EmailChallenge.expires < now - DAY).limit(256)
        db.query(EmailChallenge).filter(EmailChallenge.email.in_(stale)).delete(synchronize_session=False)
    db.commit()
