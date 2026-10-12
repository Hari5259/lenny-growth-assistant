# Security

This is an internal pilot tool. This page states what it protects against, how, and what it does not cover yet.

## Reporting a problem

Open a private security advisory on the GitHub repository (Security → Advisories → Report a vulnerability), or contact the maintainer directly. Please don't open a public issue for a vulnerability.

## Generated HTML (artifacts)

AI-generated HTML is treated as untrusted. Three independent layers, so one failing does not expose the app:

| Layer | Where | What it does |
|---|---|---|
| 1. Sanitizer | Server, `backend/app/agent/artifacts.py` | Removes `<script>`, `<iframe>`, `<object>`, `<embed>`, `<svg>`, `<math>` (with their content); forms and inputs; all `on*` event handlers; external URLs in `href`, `src`, `srcset` and CSS `url()`; `@import`. Only `#anchors` and `data:image/` URLs survive. What was removed is recorded and shown under **Security** in the viewer |
| 2. Content-Security-Policy | Injected `<meta>` in the document | `default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; form-action 'none'; base-uri 'none'; frame-src 'none'`: no network request is possible even if the sanitizer misses something |
| 3. Sandboxed iframe | Browser, `ArtifactViewer.tsx` | `<iframe sandbox="" srcdoc=...>`: no script execution, opaque origin (no cookies, storage or access to the app), no forms, pop-ups or navigation of the app |

Markdown artifacts and answers are rendered with raw HTML disabled.

Tests: `test_sanitizer_*` and `test_html_artifact_is_sanitized_end_to_end` cover script tags, event handlers, `javascript:` URLs, external images, CSS imports and forms.

## Model output and prompt injection

- Transcript excerpts are passed to the model as data inside `<source>` tags, with instructions to treat them as quotes, not commands.
- The model has no dangerous tools: no shell, no file system, no network. On the cloud path it has one read-only search tool.
- Citations are checked after generation; ids that don't match a retrieved source are removed.

## Data and secrets

- **Local by default.** With the Ollama provider, questions and chats never leave the machine. The provider is shown on every answer, so it is always clear when the cloud was used.
- `ANTHROPIC_API_KEY` is read from `.env`, which is git-ignored. It is never logged or returned by the API (`/api/config` reports only whether a key is configured).
- Telemetry in the Agent SDK is disabled.
- Logs contain request ids, routes, timings and model names. They do not contain API keys.

## Known limitations (v1)

| Limitation | Plan |
|---|---|
| No authentication: anyone who can reach port 3000 can use the app and read chats by session id | SSO and per-user authorization before any shared deployment |
| No rate limiting | Add at the reverse proxy when deployed beyond one machine |
| Postgres uses default credentials in `docker-compose.yml` | Change `POSTGRES_PASSWORD` and `DATABASE_URL` for any non-local deployment |
| Interactive (scripted) artifacts are not supported | Would need a separate origin to be safe |

Run it on a trusted network only until the first two items are done.
