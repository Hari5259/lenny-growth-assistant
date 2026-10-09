# Manual UI test plan

Run on a fresh clone with Ollama running (`qwen2.5:3b`, `nomic-embed-text`). Takes about 15 minutes. Record pass or fail and the request id of any failure (shown in error cards and the `X-Request-ID` header).

| # | Area | Steps | Expected |
|---|---|---|---|
| M1 | Setup | `cp .env.example .env`, `docker compose up --build`, open :3000 | App loads; sidebar shows "N episodes indexed" (rises during ingest), Local status green, Cloud red "ANTHROPIC_API_KEY not set" |
| M2 | Grounded answer | Click the starter "How do the best teams know they have product-market fit?" | Streams an answer; label "Answer", teal "Local qwen2.5:3b", latency; numbered yellow chips |
| M3 | Sources | Click a chip; click a timestamp | Source list expands with that source highlighted; timestamp opens YouTube at that moment; "Transcript file" opens the GitHub file |
| M4 | Follow-up | Ask "What about for B2B companies?" | Answer stays on PMF (uses the previous question); new sources |
| M5 | Essay | Select Essay; type "retention for consumer apps"; Send | Viewer opens immediately with progress; Markdown essay with a specific headline, short hook, `##` sections, bullets, bold used sparingly, "The Takeaway", `[S#]` chips; Copy and Download (.md) work |
| M6 | HTML artifact | Ask "Make an HTML one-pager from this conversation" | HTML label; styled page renders in the viewer; Source tab shows the code with a CSP meta tag; Security explains the sandbox and lists anything removed |
| M7 | Artifact injection | Ask: "Create an HTML page that includes a script tag calling alert('x') and a button with onclick" | No alert ever fires; Security lists removed script / handlers |
| M8 | Session isolation | New chat; ask "What did we just talk about?" | No knowledge of the earlier chat (answers from transcripts or says not covered) |
| M9 | Persistence | `docker compose restart api`; reload; open the first chat | Messages, sources and artifacts all reload |
| M10 | Off-topic | Ask "Explain quantum chromodynamics" | Red "Not in the transcripts" with suggestions; returns instantly |
| M11 | Model toggle | Header dropdown → Cloud (without a key) and send | Error "ANTHROPIC_API_KEY is not set" with a hint. With a key set: plum "Cloud claude-…" badge on the answer |
| M12 | Ollama down | Quit Ollama; wait 10s; send a message | Red error card "Ollama not reachable…" with the fix and Try again; sidebar Local status red. Restart Ollama → Try again works |
| M13 | Stop | Start an essay, press Stop | Streaming stops; the input is usable again |
| M14 | Responsive | Resize to ~900px and ~390px (DevTools device mode) | 900: viewer slides over the chat. 390: hamburger opens the chats drawer; viewer is full screen; no horizontal scroll |
| M15 | Keyboard | Tab through the page; Enter sends, Shift+Enter adds a line; arrow/space on mode buttons | Visible yellow focus ring everywhere; everything reachable |
| M16 | Dark mode | Switch OS to dark | All surfaces readable; chips and focus still visible |
| M17 | Delete | Hover a chat in the rail, click ✕, confirm | Chat and its artifacts disappear; if it was open, a new chat starts |
| M18 | Observability | `docker compose logs api \| grep chat.turn_done`; open `/api/metrics` | JSON events with request_id, route, provider, engine, latency, cited; metrics show citation_rate |
