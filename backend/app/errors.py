"""Typed application errors. Every failure the user can hit maps to a stable code + hint."""

from __future__ import annotations


class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"
    hint: str | None = None

    def __init__(self, message: str, *, hint: str | None = None, details: dict | None = None):
        super().__init__(message)
        self.message = message
        if hint is not None:
            self.hint = hint
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ValidationAppError(AppError):
    status_code = 422
    code = "VALIDATION_ERROR"


class DatabaseUnavailableError(AppError):
    status_code = 503
    code = "DATABASE_UNAVAILABLE"
    hint = "Check that Postgres is running and DATABASE_URL is correct (docker compose ps)."


class ProviderNotConfiguredError(AppError):
    status_code = 400
    code = "PROVIDER_NOT_CONFIGURED"
    hint = "Set ANTHROPIC_API_KEY in .env, or switch the provider to 'ollama'."


class ProviderUnavailableError(AppError):
    status_code = 503
    code = "PROVIDER_UNAVAILABLE"
    hint = "Start Ollama (`ollama serve`) and pull the model (`ollama pull <model>`)."


class ProviderTimeoutError(AppError):
    status_code = 504
    code = "PROVIDER_TIMEOUT"
    hint = "The model took too long. Try a smaller model or raise LLM_TIMEOUT_S."


class ProviderResponseError(AppError):
    status_code = 502
    code = "PROVIDER_ERROR"


class EmbeddingUnavailableError(AppError):
    status_code = 503
    code = "EMBEDDINGS_UNAVAILABLE"
    hint = "Run `ollama pull nomic-embed-text`. Retrieval falls back to keyword search meanwhile."
