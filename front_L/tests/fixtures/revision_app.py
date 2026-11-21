"""Disposable FastAPI + model fixture used only by tests/revision.browser.cjs."""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

if os.environ.get("DB_URL") != "sqlite:////tmp/folio-browser/case.db" or Path("/tmp/folio-browser/case.db").exists():
    raise RuntimeError("This fixture requires a fresh disposable database.")

import uvicorn
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from src.blog_agent.db.models import BlogTask, TaskStatus, User
from src.blog_agent.db.session import SessionLocal, init_db
from src.blog_agent.main import app
from src.blog_agent.service.auth_service import hash_password


class Model(BaseHTTPRequestHandler):
    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["content-length"])))
        schema = data.get("response_format", {}).get("json_schema", {}).get("name")
        if schema != "ReviewResult" or self.path != "/v1/chat/completions":
            self.send_error(422)
            return
        verdict = dict(passed=True, score=94, review_opinions=[], pass_reasons=["本版符合写作简报"],
                       dimension_scores=dict(outline_compliance=93, relevance=93, style_match=93,
                                             research_usage=93, logic_flow=93))
        message = dict(role="assistant", content=json.dumps(verdict, ensure_ascii=False))
        payload = dict(id="test-response", object="chat.completion", created=1, model="offline",
                       choices=[dict(index=0, message=message, finish_reason="stop")])
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


init_db()
title = "旧城漫步"
body = f"# {title}\n\n## 巷口\n\n" + "沿着熟悉的街道走过巷口，雨后的石板上映出几扇明亮的窗。" * 4
with SessionLocal.begin() as db:
    author = User(username="WriterDemo", nickname="离线作者", email="writer@example.invalid",
                  password_hash=hash_password("WriterDemo1!"), email_verified=True)
    db.add(author)
    db.flush()
    db.add(BlogTask(id=1, user_id=author.id, topic=title, selected_title=title, outline="## 巷口",
                    outline_confirmed=True, article_style="prose", word_count=150,
                    content=body, formatted_content=body, status=TaskStatus.COMPLETED))

model = ThreadingHTTPServer(("127.0.0.1", 17871), Model)
Thread(target=model.serve_forever, daemon=True).start()
app.mount("/assets", StaticFiles(directory="/app/dist/assets"))


@app.get("/{path:path}", include_in_schema=False)
def serve_ui(path: str):
    return FileResponse("/app/dist/index.html")


uvicorn.run(app, host="127.0.0.1", port=8181, log_level="warning")
