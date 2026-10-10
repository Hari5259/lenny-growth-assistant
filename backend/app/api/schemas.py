"""Request/response contracts (validated by Pydantic, published in OpenAPI at /docs)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

ProviderName = Literal["ollama", "anthropic"]
Mode = Literal["auto", "qa", "essay", "artifact"]


class ErrorBody(BaseModel):
    code: str
    message: str
    hint: str | None = None
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class CreateSessionRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-.@]+$")
    display_name: str | None = Field(default=None, max_length=100)
    user_metadata: dict[str, Any] = Field(default_factory=dict)
    provider: ProviderName | None = None
    title: str | None = Field(default=None, max_length=120)

    @field_validator("user_metadata")
    @classmethod
    def small_metadata(cls, v: dict) -> dict:
        if len(str(v)) > 2000:
            raise ValueError("user_metadata too large (max 2KB)")
        return v


class UpdateSessionRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    provider: ProviderName | None = None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: str
    title: str
    provider: str
    created_at: datetime
    updated_at: datetime
    message_count: int | None = None


class MessageOut(BaseModel):
    id: UUID
    session_id: UUID
    role: Literal["user", "assistant"]
    content: str
    route: str | None = None
    provider: str | None = None
    model: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    artifact_id: UUID | None = None


class ArtifactOut(BaseModel):
    id: UUID
    session_id: UUID
    message_id: UUID | None
    kind: Literal["markdown", "html"]
    title: str
    content: str
    sanitizer: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SessionDetail(SessionOut):
    messages: list[MessageOut]
    artifacts: list[ArtifactOut]


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    mode: Mode = "auto"
    provider: ProviderName | None = Field(default=None, description="Override the session provider for this turn")

    @field_validator("content")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("content must not be blank")
        return v.strip()


class ChatResponse(BaseModel):
    message: MessageOut
    artifact: ArtifactOut | None = None
    route: str
    provider: str | None
    model: str | None
    engine: str | None
    sources: list[dict[str, Any]]
    notices: list[str] = Field(default_factory=list)


class ProviderOut(BaseModel):
    name: str
    model: str
    label: str
    local: bool
    available: bool
    reason: str | None = None


class ConfigResponse(BaseModel):
    default_provider: str
    fallback_provider: str
    agent_engine: str
    providers: list[ProviderOut]
    modes: list[str] = ["auto", "qa", "essay", "artifact"]


class SearchHitOut(BaseModel):
    id: str
    episode_slug: str
    episode_title: str
    guest: str | None
    start_ts: str | None
    deep_link: str | None
    source_url: str
    snippet: str
    vector_score: float | None
    keyword_rank: float | None
    rrf: float


class SearchResponse(BaseModel):
    query: str
    mode: str
    grounding: str
    top_vector_score: float | None = None
    latency_ms: int
    hits: list[SearchHitOut]
