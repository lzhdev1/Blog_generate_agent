"""Registration challenges. A successful SMTP code is consumed with account creation."""
import hashlib
import hmac
import logging
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage

from fastapi import HTTPException

from config.settings import settings
from src.blog_agent.db.access_models import EmailChallenge
from src.blog_agent.service.quota_service import insert_for

logger = logging.getLogger(__name__)


def _digest(email, code):
    return hmac.new(settings.jwt_secret.encode(), f"registration:{email}:{code}".encode(),
                    hashlib.sha256).hexdigest()


def _send_mail(email, code):
    msg = EmailMessage()
    msg["Subject"] = "稿间 · 注册验证码"
    msg["From"] = settings.smtp_sender
    msg["To"] = email
    msg.set_content(f"你的注册验证码是 {code}，10 分钟内有效。")
    context = ssl.create_default_context()
    if settings.smtp_transport == "ssl":
        connection = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
    else:
        connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    with connection as smtp:
        if settings.smtp_transport == "starttls":
            smtp.starttls(context=context)
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(msg)


def require_registration():
    if settings.effective_registration == "closed":
        raise HTTPException(503, detail={"code": "registration_closed", "message": "本站暂未开放新用户注册。"})


def issue_code(db, email):
    require_registration()
    if settings.effective_registration == "test":
        return {"message": "测试模式使用页面显示的验证码", "code": settings.email_code_default}
    code = f"{secrets.randbelow(1000000):06d}"
    digest = _digest(email, code)
    values = {"digest": digest, "expires": int(time.time()) + 600, "failures": 0}
    stmt = insert_for(db, EmailChallenge).values(email=email, **values)
    db.execute(stmt.on_conflict_do_update(index_elements=["email"], set_=values))
    db.commit()
    try:
        _send_mail(email, code)
    except (OSError, smtplib.SMTPException, ValueError):
        db.query(EmailChallenge).filter_by(email=email, digest=digest).delete()
        db.commit()
        logger.warning("Registration email delivery failed")
        raise HTTPException(503, detail={"code": "mail_unavailable", "message": "验证码发送失败，请稍后重试。"})
    return {"message": "验证码已发送，请查看邮箱"}


def consume_code(db, email, code):
    require_registration()
    if settings.effective_registration == "test":
        if hmac.compare_digest(code, settings.email_code_default):
            return
    else:
        row = db.query(EmailChallenge).filter_by(email=email).with_for_update().first()
        if row and row.expires > int(time.time()) and row.failures < 5:
            if hmac.compare_digest(row.digest, _digest(email, code)):
                db.delete(row)
                return
            row.failures += 1
            db.commit()
    raise HTTPException(400, detail="邮箱验证码不正确或已过期")
