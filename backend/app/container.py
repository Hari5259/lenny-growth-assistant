"""Composition root: builds every service once and hands them to the routes."""

from __future__ import annotations

from dataclasses import dataclass

from app.agent.orchestrator import Orchestrator
from app.agent.skills import SkillRegistry
from app.config import Settings
from app.db.pool import Database
from app.db.repository import ConversationRepository
from app.llm.embeddings import Embedder, OllamaEmbedder
from app.llm.providers import ProviderRegistry
from app.retrieval.search import Retriever


@dataclass
class Container:
    settings: Settings
    db: Database
    repo: ConversationRepository
    embedder: Embedder
    retriever: Retriever
    providers: ProviderRegistry
    skills: SkillRegistry
    orchestrator: Orchestrator


def build_container(settings: Settings, *, embedder: Embedder | None = None,
                    orchestrator_kwargs: dict | None = None) -> Container:
    db = Database(settings)
    repo = ConversationRepository(db)
    embedder = embedder or OllamaEmbedder(settings)
    retriever = Retriever(settings, db, embedder)
    providers = ProviderRegistry(settings)
    skills = SkillRegistry(settings.skills_dir or None)
    orchestrator = Orchestrator(settings, repo, retriever, providers, skills, **(orchestrator_kwargs or {}))
    return Container(settings, db, repo, embedder, retriever, providers, skills, orchestrator)
