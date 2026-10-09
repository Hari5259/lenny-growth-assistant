"""Generation engines.

SdkEngine    - Claude Agent SDK (`claude_agent_sdk.query`). Works with both providers:
               * anthropic: talks to api.anthropic.com; also gets an in-process MCP tool
                 `search_transcripts` so the agent can run extra lookups when the pre-fetched
                 sources are not enough (agentic retrieval).
               * ollama:    ANTHROPIC_BASE_URL points at Ollama's Anthropic-compatible
                 endpoint; tools are disabled because small local models misuse them.
DirectEngine - plain streaming HTTP to Ollama /api/chat or Anthropic /v1/messages. Used when
               AGENT_ENGINE=direct, and as automatic fallback if the SDK cannot start.

Both engines yield text deltas and share the same skill prompts, so behaviour is comparable.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from typing import AsyncIterator, Awaitable, Callable, Protocol

from app.config import Settings
from app.errors import ProviderResponseError, ProviderTimeoutError, ProviderUnavailableError
from app.llm.clients import stream_anthropic, stream_ollama
from app.llm.providers import ProviderSpec
from app.logging_setup import get_logger

log = get_logger(__name__)

ToolSearch = Callable[[str], Awaitable[str]]


@dataclass
class GenerationRequest:
    system: str
    messages: list[dict]  # [{"role": "user"|"assistant", "content": str}], last is the user turn
    provider: ProviderSpec
    max_tokens: int
    search_tool: ToolSearch | None = None
    tool_calls: list[str] = field(default_factory=list)


class Engine(Protocol):
    name: str

    def stream(self, req: GenerationRequest) -> AsyncIterator[str]: ...


class DirectEngine:
    name = "direct"

    def __init__(self, settings: Settings):
        self.settings = settings

    async def stream(self, req: GenerationRequest) -> AsyncIterator[str]:
        fn = stream_ollama if req.provider.name == "ollama" else stream_anthropic
        async for piece in fn(self.settings, req.provider, req.system, req.messages, req.max_tokens):
            yield piece


def _flatten_history(messages: list[dict]) -> str:
    """The SDK takes a single prompt per call; we persist history ourselves in Postgres
    (sessions are independent and survive restarts), so earlier turns are inlined."""
    *history, current = messages
    if not history:
        return current["content"]
    lines = ["<conversation_history>"]
    for m in history:
        lines.append(f"[{m['role']}]\n{m['content']}\n")
    lines.append("</conversation_history>\n")
    lines.append(current["content"])
    return "\n".join(lines)


class SdkEngine:
    name = "sdk"

    def __init__(self, settings: Settings):
        self.settings = settings
        self._workdir = tempfile.mkdtemp(prefix="lenny-agent-")

    def _env(self, provider: ProviderSpec) -> dict[str, str]:
        env = {
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_TELEMETRY": "1",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(self.settings.llm_max_tokens),
        }
        if provider.name == "ollama":
            env.update({"ANTHROPIC_BASE_URL": self.settings.ollama_base_url,
                        "ANTHROPIC_AUTH_TOKEN": "ollama", "ANTHROPIC_API_KEY": ""})
        else:
            env.update({"ANTHROPIC_API_KEY": self.settings.anthropic_api_key,
                        "ANTHROPIC_BASE_URL": self.settings.anthropic_base_url})
        return env

    def _options(self, req: GenerationRequest):
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server, tool

        use_tools = req.provider.name == "anthropic" and req.search_tool is not None
        mcp_servers: dict = {}
        allowed: list[str] = []
        if use_tools:
            search = req.search_tool

            @tool("search_transcripts",
                  "Search Lenny's Podcast transcripts for more evidence. Returns numbered excerpts "
                  "you may cite by their [S#] ids.",
                  {"query": str})
            async def search_transcripts(args: dict) -> dict:
                req.tool_calls.append(args.get("query", ""))
                text = await search(args.get("query", ""))
                return {"content": [{"type": "text", "text": text}]}

            mcp_servers = {"lenny": create_sdk_mcp_server("lenny", tools=[search_transcripts])}
            allowed = ["mcp__lenny__search_transcripts"]

        return ClaudeAgentOptions(
            system_prompt=req.system,
            model=req.provider.model,
            tools=[],                     # no built-in Claude Code tools (no shell, no files)
            allowed_tools=allowed,
            mcp_servers=mcp_servers,
            max_turns=4 if use_tools else 1,
            include_partial_messages=True,
            setting_sources=[],           # ignore any user/project settings on the host
            cwd=self._workdir,
            env=self._env(req.provider),
            permission_mode="bypassPermissions" if use_tools else None,
        )

    async def stream(self, req: GenerationRequest) -> AsyncIterator[str]:
        try:
            from claude_agent_sdk import (AssistantMessage, CLINotFoundError, ProcessError,
                                          ResultMessage, StreamEvent, TextBlock, query)
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailableError("claude-agent-sdk not installed") from exc

        emitted_any = False
        streamed_this_turn = False
        try:
            async for msg in query(prompt=_flatten_history(req.messages), options=self._options(req)):
                if isinstance(msg, StreamEvent):
                    ev = msg.event or {}
                    if ev.get("type") == "message_start":
                        streamed_this_turn = False
                    if ev.get("type") == "content_block_delta":
                        text = (ev.get("delta") or {}).get("text")
                        if text:
                            emitted_any = streamed_this_turn = True
                            yield text
                elif isinstance(msg, AssistantMessage) and not streamed_this_turn:
                    # provider without partial streaming: emit the full text block once
                    for block in msg.content:
                        if isinstance(block, TextBlock) and block.text:
                            emitted_any = True
                            yield block.text
                elif isinstance(msg, ResultMessage):
                    if msg.is_error:
                        raise ProviderResponseError(f"Agent SDK error: {msg.result or msg.subtype}")
                    log.info("agent.sdk_result", extra={"turns": msg.num_turns, "cost_usd": msg.total_cost_usd,
                                                         "duration_ms": msg.duration_ms})
        except CLINotFoundError as exc:
            raise ProviderUnavailableError("Claude Agent SDK CLI not found", hint="pip install claude-agent-sdk") from exc
        except ProcessError as exc:
            raise ProviderResponseError(f"Agent SDK process failed: {exc}") from exc
        if not emitted_any:
            raise ProviderResponseError("Agent SDK returned no text")


async def stream_with_timeout(gen: AsyncIterator[str], first_token_s: float, total_s: float) -> AsyncIterator[str]:
    """Enforce a time-to-first-token and a total budget on any engine stream."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + total_s
    first = True
    it = gen.__aiter__()
    while True:
        budget = min(first_token_s if first else total_s, deadline - loop.time())
        if budget <= 0:
            raise ProviderTimeoutError(f"Generation exceeded {total_s:.0f}s")
        try:
            piece = await asyncio.wait_for(it.__anext__(), timeout=budget)
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError as exc:
            what = "first token" if first else "generation"
            raise ProviderTimeoutError(f"Model timed out waiting for {what}") from exc
        first = False
        yield piece


def build_engine(name: str, settings: Settings) -> Engine:
    return SdkEngine(settings) if name == "sdk" else DirectEngine(settings)

