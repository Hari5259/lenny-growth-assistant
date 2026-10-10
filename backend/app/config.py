"""Central configuration. Every tunable lives here and is read from environment variables.

Switching the model is a configuration change only: set LLM_PROVIDER / OLLAMA_MODEL /
ANTHROPIC_MODEL in .env (or pick a provider per session in the UI).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["ollama", "anthropic"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_env: str = "local"
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # --- Database ---
    database_url: str = "postgresql://lenny:lenny@localhost:5432/lenny"
    db_pool_min: int = 1
    db_pool_max: int = 10
    db_connect_timeout_s: float = 5.0

    # --- LLM provider selection ---
    llm_provider: Provider = "ollama"
    llm_fallback_provider: Provider | Literal["none"] = "none"
    agent_engine: Literal["sdk", "direct"] = "sdk"
    agent_engine_fallback: bool = True  # if the SDK engine fails before streaming, retry with direct
    llm_timeout_s: float = 180.0
    llm_max_tokens: int = 2500
    llm_temperature: float = 0.3

    # --- Ollama (local) ---
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_num_ctx: int = 8192
    ollama_keep_alive: str = "30m"  # how long Ollama keeps the model in GPU memory after a request
    ollama_warmup: bool = True  # load the chat + embedding models when the API starts

    # --- Anthropic (cloud) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_base_url: str = "https://api.anthropic.com"

    # --- Embeddings / retrieval ---
    embed_model: str = "nomic-embed-text"
    embed_dim: int = 768
    embed_batch_size: int = 32
    retrieval_top_k: int = 6
    retrieval_top_k_local: int = 4  # fewer excerpts for small local models: shorter prompt, faster answer
    retrieval_candidates: int = 24
    retrieval_max_per_episode: int = 2
    retrieval_min_vector_score: float = 0.50
    history_turns: int = 6

    # --- Ingestion ---
    transcripts_repo: str = "https://github.com/ChatPRD/lennys-podcast-transcripts.git"
    transcripts_dir: str = "./data/lennys-podcast-transcripts"
    transcripts_github_base: str = (
        "https://github.com/ChatPRD/lennys-podcast-transcripts/blob/main/episodes"
    )
    ingest_limit: int = 0  # 0 = all episodes
    chunk_target_chars: int = 1800
    chunk_max_chars: int = 2600

    skills_dir: str = Field(default="", description="Override skills folder; empty = bundled")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def anthropic_configured(self) -> bool:
        return bool(self.anthropic_api_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
