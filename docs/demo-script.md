# Demo video script (2–3 minutes)

Recorded on camera, with the app running locally on the reference laptop (Windows 11, RTX 3050, `qwen2.5:3b`).

## Before recording

1. `docker compose up -d` and wait until the sidebar shows **303 episodes indexed** with green dots.
2. Ask one warm-up question off camera, so the model is loaded and the first on-camera answer is fast.
3. Close other heavy apps. Set browser zoom to 110% so text is readable in the video.
4. Have a second tab open at `http://localhost:8000/api/metrics`.

## Script

| Time | Show | Say (in your own words) |
|---|---|---|
| 0:00–0:15 | Your face, then the welcome screen | "This is the Lenny Growth Assistant. It answers product and growth questions only from Lenny's Podcast transcripts, and every claim links back to the guest and the minute in the episode." |
| 0:15–0:50 | Click **How do the best teams know they have product-market fit?** Expand sources, click a YouTube link | "The answer streams from a local model through the Claude Agent SDK. The yellow numbers are sources. Here is the guest, the quote, and the link opens YouTube at that exact moment." |
| 0:50–1:05 | Ask a follow-up: **What about for B2B?** | "Follow-ups keep context within this chat. Each new chat is an independent session stored in Postgres." |
| 1:05–1:25 | Ask **What is the boiling point of tungsten?** | "If the transcripts don't cover something, it says so and suggests real questions. The model is not called at all, so it cannot make something up. On the full index this refuses 100% of off-topic questions." |
| 1:25–1:55 | Pick **Essay** mode: *Write an essay on building growth loops for a seed-stage PM* | "Essays follow the Ship 30 for 30 format, defined in a SKILL.md file that a non-engineer can edit. It opens in the side panel, with copy and download." |
| 1:55–2:15 | Pick **Artifact**: *Make an HTML one-pager on running a great onboarding experiment*. Click **Security** | "HTML artifacts render in a locked sandbox: scripts, external links and forms are removed on the server, and the iframe has no permissions." |
| 2:15–2:35 | Model dropdown (Local / Cloud), then the metrics tab | "Local or cloud is a per-chat switch, and the model is shown on every answer. Metrics show citation rate, no-answer rate and latency." |
| 2:35–2:50 | Your face | "Everything runs with one `docker compose up`. The README, PRD, architecture and the agent transcripts, including what went wrong, are in the repo. Thanks." |

## Tips

- If an answer is slow on camera, keep talking about the sources panel while it streams; don't cut.
- Upload to YouTube as **Unlisted**, then paste the link in the submission form.
