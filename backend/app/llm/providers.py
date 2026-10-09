"""Provider registry: which LLMs exist, which are usable right now, and fallback resolution.

The selected provider comes from (highest priority first):
  1. the per-message / per-session choice made in the UI
  2. LLM_PROVIDER in .env
If the chosen provider is unusable and LLM_FALLBACK_PROVIDER is set, we fall back and say so.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.errors import ProviderNotConfiguredError, ProviderUnavailableError
from app.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class ProviderSpec:
    name: str  # ollama | anthropic
    model: str
    label: str
    local: bool


@dataclass
class ProviderStatus:
    spec: ProviderSpec
    available: bool
    reason: str | None = None

    def to_dict(self) -> dict:
        return {"name": self.spec.name, "model": self.spec.model, "label": self.spec.label,
                "local": self.spec.local, "available": self.available, "reason": self.reason}


class ProviderRegistry:
    CACHE_TTL_S = 10.0

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self.settings = settings
        self.http = http or httpx.AsyncClient(timeout=3.0)
        self._cache: dict[str, tuple[float, ProviderStatus]] = {}

    def spec(self, name: str) -> ProviderSpec:
        s = self.settings
        if name == "ollama":
            return ProviderSpec("ollama", s.ollama_model, f"Local · Ollama · {s.ollama_model}", True)
        if name == "anthropic":
            return ProviderSpec("anthropic", s.anthropic_model, f"Cloud · Claude · {s.anthropic_model}", False)
        raise ProviderNotConfiguredError(f"Unknown provider '{name}'", hint="Use 'ollama' or 'anthropic'.")

    async def status(self, name: str, *, fresh: bool = False) -> ProviderStatus:
        cached = self._cache.get(name)
        if cached and not fresh and time.monotonic() - cached[0] < self.CACHE_TTL_S:
            return cached[1]
        spec = self.spec(name)
        if name == "anthropic":
            st = ProviderStatus(spec, self.settings.anthropic_configured,
                                None if self.settings.anthropic_configured else "ANTHROPIC_API_KEY not set")
        else:
            st = await self._ollama_status(spec)
        self._cache[name] = (time.monotonic(), st)
        return st

    async def _ollama_status(self, spec: ProviderSpec) -> ProviderStatus:
        try:
            resp = await self.http.get(f"{self.settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return ProviderStatus(spec, False, f"Ollama not reachable at {self.settings.ollama_base_url} ({exc.__class__.__name__})")
        names = {m.get("name", "") for m in resp.json().get("models", [])}
        wanted = spec.model if ":" in spec.model else f"{spec.model}:latest"
        if wanted not in names and spec.model not in names:
            return ProviderStatus(spec, False, f"Model '{spec.model}' not pulled. Run: ollama pull {spec.model}")
        return ProviderStatus(spec, True)

    async def all_statuses(self) -> list[ProviderStatus]:
        return [await self.status("ollama"), await self.status("anthropic")]

    async def resolve(self, requested: str | None) -> tuple[ProviderSpec, str | None]:
        """Return (provider to use, fallback note or None). Raises a typed error if none usable."""
        primary = requested or self.settings.llm_provider
        st = await self.status(primary)
        if st.available:
            return st.spec, None
        fb = self.settings.llm_fallback_provider
        if fb != "none" and fb != primary:
            fb_st = await self.status(fb)
            if fb_st.available:
                note = f"{primary} unavailable ({st.reason}); fell back to {fb}."
                log.warning("llm.provider_fallback", extra={"from": primary, "to": fb, "reason": st.reason})
                return fb_st.spec, note
        if primary == "anthropic":
            raise ProviderNotConfiguredError(st.reason or "Anthropic not configured")
        raise ProviderUnavailableError(st.reason or "Ollama unavailable",
                                       hint=f"Start Ollama and run `ollama pull {self.settings.ollama_model}`.")
