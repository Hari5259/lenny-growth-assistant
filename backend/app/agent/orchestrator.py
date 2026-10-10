"""Orchestrator: one user turn end-to-end.

route -> retrieve -> (gate) -> resolve provider -> generate (stream) -> extract artifact
-> validate citations -> persist -> emit events.

Events (also the SSE contract, see api/schemas.py):
  meta     {route, route_reason, provider, model, engine, retrieval, sources, notices}
  delta    {text}
  artifact {artifact}
  done     {message}
  error    {error: {code, message, hint}}
"""

from __future__ import annotations

import time
from typing import AsyncIterator
from uuid import UUID

from app.agent.artifacts import extract_artifact
from app.agent.engines import (DirectEngine, Engine, GenerationRequest, build_engine,
                               stream_with_timeout)
from app.agent.prompts import (NO_ANSWER_TEXT, append_sources_section, build_messages, build_system,
                               citation_check,
                               format_source, retrieval_query, strip_invalid_citations)
from app.agent.router import route_message
from app.agent.skills import SkillRegistry
from app.config import Settings
from app.db.repository import ConversationRepository
from app.errors import AppError, ProviderResponseError
from app.llm.providers import ProviderRegistry
from app.logging_setup import get_logger, session_id_var
from app.retrieval.search import Retriever, hit_to_source

log = get_logger(__name__)
FIRST_TOKEN_TIMEOUT_S = 90.0


def _session_title(text: str) -> str:
    t = " ".join(text.split())
    return t[:60] + ("…" if len(t) > 60 else "")


class Orchestrator:
    def __init__(self, settings: Settings, repo: ConversationRepository, retriever: Retriever,
                 providers: ProviderRegistry, skills: SkillRegistry, engine: Engine | None = None,
                 fallback_engine: Engine | None = None):
        self.settings = settings
        self.repo = repo
        self.retriever = retriever
        self.providers = providers
        self.skills = skills
        self.engine = engine or build_engine(settings.agent_engine, settings)
        self.fallback_engine = fallback_engine or (
            DirectEngine(settings) if settings.agent_engine_fallback and self.engine.name != "direct" else None
        )

    async def _search_tool(self, offset: int, extra_sources: list[dict]):
        async def search(query: str) -> str:
            res = await self.retriever.search(query, top_k=4)
            lines = []
            for h in res.hits:
                idx = offset + len(extra_sources) + 1
                extra_sources.append(hit_to_source(idx, h))
                lines.append(format_source(idx, h))
            return "\n".join(lines) or "No matching excerpts."
        return search

    async def _generate(self, req: GenerationRequest, notices: list[str]) -> AsyncIterator[tuple[str, str]]:
        """Yields (engine_name, text). Falls back to the direct engine if the primary fails
        before producing any output (e.g. SDK CLI cannot start, endpoint incompatible)."""
        produced = False
        try:
            async for piece in stream_with_timeout(self.engine.stream(req), FIRST_TOKEN_TIMEOUT_S,
                                                   self.settings.llm_timeout_s):
                produced = True
                yield self.engine.name, piece
            return
        except AppError as exc:
            if produced or not self.fallback_engine or exc.code == "PROVIDER_TIMEOUT":
                raise
            log.warning("agent.engine_fallback", extra={"from": self.engine.name,
                                                         "to": self.fallback_engine.name, "error": exc.message})
            notices.append(f"Agent SDK engine failed ({exc.code}); answered with the direct engine.")
        async for piece in stream_with_timeout(self.fallback_engine.stream(req), FIRST_TOKEN_TIMEOUT_S,
                                               self.settings.llm_timeout_s):
            yield self.fallback_engine.name, piece

    async def run(self, session_id: UUID, user_text: str, mode: str = "auto",
                  provider: str | None = None) -> AsyncIterator[dict]:
        session_id_var.set(str(session_id))
        started = time.perf_counter()
        session = await self.repo.get_session(session_id)
        history_rows = await self.repo.list_messages(session_id, limit=self.settings.history_turns)
        history = [{"role": r["role"], "content": r["content"]} for r in history_rows]
        await self.repo.add_message(session_id, "user", user_text, meta={"mode": mode})
        if session["title"] == "New chat":
            await self.repo.update_session(session_id, title=_session_title(user_text))

        decision = route_message(user_text, mode)
        skill = self.skills.for_route(decision.route)
        notices: list[str] = []
        meta: dict = {"route_reason": decision.reason, "mode": mode}

        try:
            requested = provider or session["provider"]
            top_k = (self.settings.retrieval_top_k_local if requested == "ollama"
                     else self.settings.retrieval_top_k)
            retrieval = await self.retriever.search(retrieval_query(user_text, history, decision.route),
                                                    top_k=top_k)
            if retrieval.mode == "keyword":
                notices.append("Semantic search unavailable; using keyword search only.")
            sources = [hit_to_source(i, h) for i, h in enumerate(retrieval.hits, 1)]
            meta["retrieval"] = retrieval.stats()

            # Grounding gate: do not call the model when there is nothing to ground on.
            if retrieval.grounding == "none" and (decision.route == "qa" or not history):
                meta.update({"latency_ms": int((time.perf_counter() - started) * 1000), "cited": False})
                yield {"type": "meta", "route": "no_answer", "route_reason": "no supporting transcripts",
                       "provider": None, "model": None, "engine": None, "retrieval": meta["retrieval"],
                       "sources": [], "notices": notices}
                yield {"type": "delta", "text": NO_ANSWER_TEXT}
                msg = await self.repo.add_message(session_id, "assistant", NO_ANSWER_TEXT,
                                                  route="no_answer", sources=[], meta=meta)
                yield {"type": "done", "message": msg}
                return

            spec, fb_note = await self.providers.resolve(provider or session["provider"])
            if fb_note:
                notices.append(fb_note)
            yield {"type": "meta", "route": decision.route, "route_reason": decision.reason,
                   "provider": spec.name, "model": spec.model, "engine": self.engine.name,
                   "retrieval": meta["retrieval"], "sources": sources, "notices": notices}

            extra_sources: list[dict] = []
            req = GenerationRequest(
                system=build_system(skill, retrieval),
                messages=build_messages(user_text, history, retrieval),
                provider=spec,
                max_tokens=min(skill.max_tokens, self.settings.llm_max_tokens),
                search_tool=await self._search_tool(len(sources), extra_sources),
            )
            parts: list[str] = []
            engine_used = self.engine.name
            gen_started = time.perf_counter()
            first_token_ms: int | None = None
            async for engine_used, piece in self._generate(req, notices):
                if first_token_ms is None:
                    first_token_ms = int((time.perf_counter() - gen_started) * 1000)
                parts.append(piece)
                yield {"type": "delta", "text": piece}
            generation_ms = int((time.perf_counter() - gen_started) * 1000)
            full = "".join(parts).strip()
            if not full:
                raise ProviderResponseError("The model returned an empty response")

            all_sources = sources + extra_sources
            artifact_row = None
            artifact, chat_text = extract_artifact(full, decision.route)
            if artifact and decision.route == "artifact" and artifact.kind == "markdown" and not artifact.content:
                artifact = None
            stored_text = strip_invalid_citations(chat_text if artifact else full, len(all_sources))
            cite = citation_check((artifact.content if artifact else "") + "\n" + stored_text, len(all_sources))
            if artifact and artifact.kind == "markdown" and not cite["cited"] and all_sources:
                artifact.content = append_sources_section(artifact.content, all_sources)
                notices.append("The model did not cite inline; the source excerpts are listed at the end.")
            meta.update({
                **cite, "engine": engine_used, "notices": notices, "tool_calls": req.tool_calls,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "output_chars": len(full),
                # where the time went: retrieval vs model start-up vs writing
                "timings": {"retrieval_ms": retrieval.latency_ms, "first_token_ms": first_token_ms,
                            "generation_ms": generation_ms},
            })
            if not stored_text and artifact:
                stored_text = f"Created **{artifact.title}** — open it in the Artifact Viewer."
            msg = await self.repo.add_message(
                session_id, "assistant", stored_text, route=decision.route, provider=spec.name,
                model=spec.model, sources=all_sources, meta=meta,
            )
            if artifact:
                artifact_row = await self.repo.add_artifact(session_id, msg["id"], artifact.kind,
                                                            artifact.title, artifact.content, artifact.sanitizer)
                log.info("artifact.created", extra={"kind": artifact.kind, "chars": len(artifact.content),
                                                    "sanitizer": artifact.sanitizer.get("removed_tags")})
                yield {"type": "artifact", "artifact": artifact_row}
            elif decision.route == "artifact":
                log.warning("artifact.missing", extra={"output_chars": len(full)})
            log.info("chat.turn_done", extra={"route": decision.route, "provider": spec.name,
                                              "engine": engine_used, "latency_ms": meta["latency_ms"],
                                              "cited": cite["cited"], "sources": len(all_sources)})
            msg["artifact_id"] = artifact_row["id"] if artifact_row else None
            yield {"type": "done", "message": msg}

        except AppError as exc:
            log.error("chat.turn_failed", extra={"code": exc.code, "error": exc.message})
            meta.update({"error": {"code": exc.code, "message": exc.message},
                         "latency_ms": int((time.perf_counter() - started) * 1000)})
            try:
                await self.repo.add_message(session_id, "assistant", f"Error: {exc.message}",
                                            route=decision.route, meta=meta)
            except AppError:
                pass
            yield {"type": "error", "error": {"code": exc.code, "message": exc.message, "hint": exc.hint}}

