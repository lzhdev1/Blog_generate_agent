"""Review a private working copy without touching the version currently shown to readers."""
from src.blog_agent.clients.provider_budget import provider_run
from src.blog_agent.agent.evidence import requires_sources, source_records
from src.blog_agent.agent.nodes.quality_gate import count_chars
from src.blog_agent.agent.tools.search_tool import web_search
from src.blog_agent.db.models import BlogTask, EditorialDraft
from src.blog_agent.service import job_queue


def review_private_draft(claim, task_id, *, sessions):
    from src.blog_agent.service.agent_service import _CONTENT_GATE, _failure_message

    with sessions() as db:
        task = db.get(BlogTask, task_id)
        draft = db.get(EditorialDraft, task_id)
        if not task or not draft or draft.job_id != claim.job_id:
            raise job_queue.LeaseLost()
        fields = ("topic", "purpose", "selected_title", "article_style", "article_style_custom",
                  "need_image", "word_count", "level", "extra_requirements", "content_extra_requirements", "outline",
                  "content_research", "evidence_sources")
        state = {field: getattr(task, field) for field in fields}
        if task.word_count is None:
            # Imported manuscripts can predate the length setting. A local correction
            # should be assessed against the edition the author opened.
            state["word_count"] = min(10000, max(100, count_chars(task.formatted_content or task.content or "")))
        state.update(content=draft.content, editor_revision=True, force_review=True)
        sources = draft.evidence_sources or state["evidence_sources"] or []
        query = draft.source_query
        if not query and not sources and requires_sources(state):
            query = task.selected_title or task.topic
    report = error = None
    try:
        with provider_run():
            if query:
                result = web_search.invoke({"query": query})
                if result["status"] == "ok":
                    sources = source_records([{"role": "tool", "search_result": result}], existing=sources,
                                             content=state["content"])
                elif result["status"] == "unavailable":
                    error = "补查服务暂时不可用。已保留修订稿和已有来源，请稍后重试。"
                else:
                    report = {"passed": False, "review_opinions": [{
                        "point": 1, "where": "补查资料", "why": "本次检索没有找到可核验的记录。",
                        "expected": "更换检索词，或修改需要外部依据的论断后重新提交。",
                    }]}
            state["evidence_sources"] = sources
            if error is None and report is None:
                report = _CONTENT_GATE(state)["review_result"]
    except Exception as exc:
        error = _failure_message(exc) or "审核服务暂时不可用，请稍后重试。"
    with sessions.begin() as db:
        job_queue.finish_editorial_review(db, claim, report, error, sources)
