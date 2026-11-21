"""Bound API request memory and keep database errors out of client responses."""
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, TimeoutError as DatabaseTimeout
from starlette.datastructures import MutableHeaders

MAX_BODY_BYTES = 256 * 1024


class APIRequestLimits:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)

        async def protected_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("Cache-Control", "private, no-store")
                headers.setdefault("X-Content-Type-Options", "nosniff")
            await send(message)

        if scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, protected_send)

        async def reject():
            response = JSONResponse({"detail": "请求体过大，请缩短内容后再试。"}, status_code=413)
            await response(scope, receive, protected_send)

        for name, value in scope["headers"]:
            if name == b"content-length" and (len(value) > 10 or not value.isdigit() or int(value) > MAX_BODY_BYTES):
                return await reject()

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                return await reject()
            body.extend(chunk)
            if not message.get("more_body"):
                break
        sent = False

        async def replay():
            nonlocal sent
            if sent:
                return await receive()
            sent = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        return await self.app(scope, replay, protected_send)


def install_http_limits(app):
    app.add_middleware(APIRequestLimits)

    async def database_unavailable(request, exc):
        return JSONResponse(status_code=503, content={"detail": {
            "code": "database_unavailable", "message": "存储服务暂时繁忙，请稍后重试。"
        }}, headers={"Retry-After": "5"})

    app.add_exception_handler(OperationalError, database_unavailable)
    app.add_exception_handler(DatabaseTimeout, database_unavailable)
