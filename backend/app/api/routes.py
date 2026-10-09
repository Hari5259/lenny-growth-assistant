"""HTTP routes. Thin: validation in schemas, behaviour in services."""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.api.schemas import (ArtifactOut, ChatResponse, ConfigResponse, CreateSessionRequest,
                             ErrorResponse, SearchResponse, SendMessageRequest,
                             SessionDetail, SessionOut, UpdateSessionRequest)
from app.container import Container
from app.errors import AppError
from app.retrieval.search import hit_to_source

router = APIRouter()
ERRORS = {code: {"model": ErrorResponse} for code in (400, 404, 422, 502, 503, 504)}


def c(request: Request) -> Container:
    return request.app.state.container


# ---------------- health ----------------
@router.get("/health", tags=["health"], summary="Liveness: the process is up")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"], summary="Readiness: dependencies + knowledge base")
async def ready(request: Request, response: Response) -> dict:
    ct = c(request)
    db_ok = await ct.db.ping()
    providers = [p.to_dict() for p in await ct.providers.all_statuses()]
    kb = None
    if db_ok:
        try:
            async with ct.db.connection() as conn:
                cur = await conn.execute(
                    "SELECT (SELECT count(*) FROM episodes) AS episodes, (SELECT count(*) FROM chunks) AS chunks,"
                    " (SELECT count(*) FROM chunks WHERE embedding IS NOT NULL) AS embedded_chunks")
                kb = await cur.fetchone()
        except AppError:
            db_ok = False
    default = next(p for p in providers if p["name"] == ct.settings.llm_provider)
    checks = {
        "database": {"ok": db_ok},
        "knowledge_base": {"ok": bool(kb and kb["chunks"]), **(kb or {}),
                           "hint": None if kb and kb["chunks"] else "Run the ingest job: docker compose run --rm ingest"},
        "default_provider": {"ok": default["available"], **default},
        "providers": providers,
    }
    ok = db_ok and checks["knowledge_base"]["ok"] and default["available"]
    response.status_code = 200 if ok else 503
    return {"status": "ready" if ok else "degraded", "checks": checks}


# ---------------- config ----------------
@router.get("/api/config", response_model=ConfigResponse, tags=["config"])
async def get_config(request: Request) -> ConfigResponse:
    ct = c(request)
    return ConfigResponse(
        default_provider=ct.settings.llm_provider,
        fallback_provider=ct.settings.llm_fallback_provider,
        agent_engine=ct.settings.agent_engine,
        providers=[p.to_dict() for p in await ct.providers.all_statuses()],
    )


@router.get("/api/metrics", tags=["config"], summary="Operational + product success metrics")
async def metrics(request: Request) -> dict:
    return await c(request).repo.metrics()


# ---------------- sessions ----------------
@router.post("/api/sessions", response_model=SessionOut, status_code=201, tags=["sessions"], responses=ERRORS)
async def create_session(body: CreateSessionRequest, request: Request) -> dict:
    ct = c(request)
    await ct.repo.upsert_user(body.user_id, body.display_name, body.user_metadata)
    return await ct.repo.create_session(body.user_id, body.provider or ct.settings.llm_provider, body.title)


@router.get("/api/sessions", response_model=list[SessionOut], tags=["sessions"], responses=ERRORS)
async def list_sessions(request: Request, user_id: str = Query(min_length=1, max_length=100)) -> list[dict]:
    return await c(request).repo.list_sessions(user_id)


@router.get("/api/sessions/{session_id}", response_model=SessionDetail, tags=["sessions"], responses=ERRORS)
async def get_session(session_id: UUID, request: Request) -> dict:
    repo = c(request).repo
    session = await repo.get_session(session_id)
    artifacts = await repo.list_artifacts(session_id)
    by_message = {a["message_id"]: a["id"] for a in artifacts}
    messages = [{**m, "artifact_id": by_message.get(m["id"])} for m in await repo.list_messages(session_id)]
    return {**session, "messages": messages, "artifacts": artifacts}


@router.patch("/api/sessions/{session_id}", response_model=SessionOut, tags=["sessions"], responses=ERRORS)
async def update_session(session_id: UUID, body: UpdateSessionRequest, request: Request) -> dict:
    return await c(request).repo.update_session(session_id, title=body.title, provider=body.provider)


@router.delete("/api/sessions/{session_id}", status_code=204, tags=["sessions"], responses=ERRORS)
async def delete_session(session_id: UUID, request: Request) -> Response:
    await c(request).repo.delete_session(session_id)
    return Response(status_code=204)


# ---------------- chat ----------------
@router.post("/api/sessions/{session_id}/messages", response_model=ChatResponse, tags=["chat"],
             responses=ERRORS, summary="Send a message and wait for the full answer")
async def send_message(session_id: UUID, body: SendMessageRequest, request: Request) -> dict:
    ct = c(request)
    await ct.repo.get_session(session_id)  # 404 before doing any work
    meta, artifact, message = {}, None, None
    async for ev in ct.orchestrator.run(session_id, body.content, body.mode, body.provider):
        if ev["type"] == "meta":
            meta = ev
        elif ev["type"] == "artifact":
            artifact = ev["artifact"]
        elif ev["type"] == "done":
            message = ev["message"]
        elif ev["type"] == "error":
            err = ev["error"]
            exc = AppError(err["message"], hint=err.get("hint"))
            exc.code = err["code"]
            exc.status_code = {"PROVIDER_NOT_CONFIGURED": 400, "PROVIDER_TIMEOUT": 504,
                               "PROVIDER_ERROR": 502}.get(err["code"], 503)
            raise exc
    return {"message": message, "artifact": artifact, "route": meta.get("route"),
            "provider": meta.get("provider"), "model": meta.get("model"), "engine": meta.get("engine"),
            "sources": meta.get("sources", []), "notices": meta.get("notices", [])}


def _sse(event: dict) -> str:
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"


@router.post("/api/sessions/{session_id}/messages/stream", tags=["chat"], responses=ERRORS,
             summary="Send a message and stream the answer as Server-Sent Events")
async def stream_message(session_id: UUID, body: SendMessageRequest, request: Request) -> StreamingResponse:
    ct = c(request)
    await ct.repo.get_session(session_id)

    async def gen():
        async for ev in ct.orchestrator.run(session_id, body.content, body.mode, body.provider):
            if await request.is_disconnected():
                break
            yield _sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- artifacts ----------------
@router.get("/api/sessions/{session_id}/artifacts", response_model=list[ArtifactOut], tags=["artifacts"])
async def list_artifacts(session_id: UUID, request: Request) -> list[dict]:
    return await c(request).repo.list_artifacts(session_id)


@router.get("/api/artifacts/{artifact_id}", response_model=ArtifactOut, tags=["artifacts"], responses=ERRORS)
async def get_artifact(artifact_id: UUID, request: Request) -> dict:
    return await c(request).repo.get_artifact(artifact_id)


# ---------------- retrieval debug ----------------
@router.get("/api/search", response_model=SearchResponse, tags=["retrieval"],
            summary="Inspect retrieval directly (no LLM) - useful for debugging grounding")
async def search(request: Request, q: str = Query(min_length=2, max_length=500),
                 k: int = Query(6, ge=1, le=20)) -> dict:
    res = await c(request).retriever.search(q, top_k=k)
    return {"query": q, "mode": res.mode, "grounding": res.grounding, "latency_ms": res.latency_ms,
            "hits": [hit_to_source(i, h) for i, h in enumerate(res.hits, 1)]}

