# Design

## 1. Principles

1. **Trust is visible.** The product's value is "this is what an operator actually said". Citations are the most prominent element after the answer text: highlighter-yellow numbered chips, each opening the source with guest, episode, quote and a timestamp link to the exact moment on YouTube.
2. **Reading surfaces read like reading.** Answers and essays use a serif (Newsreader) at a comfortable size, line-height and measure. The interface around them uses a quiet sans (IBM Plex Sans).
3. **No prompt knowledge needed.** Four plain modes (Auto, Ask, Essay, Artifact) replace prompt engineering. Starter questions show what good questions look like.
4. **Say what is happening, especially when it goes wrong.** Every state has words: indexing, thinking, writing the artifact, keyword-only fallback, model unavailable (with the fix).
5. **One bold element.** The highlighter accent is reserved for citations, the active mode, focus rings and the artifact card edge. Everything else is navy, white and fog.

## 2. Visual system

| Token | Light | Dark | Use |
|---|---|---|---|
| `--fog` | `#EEF1F4` | `#0F1622` | App background, rail |
| `--paper` | `#FFFFFF` | `#172131` | Answers, viewer, inputs |
| `--ink` | `#1B2A41` | `#E5EAF1` | Text, primary buttons, brand |
| `--hl` | `#F2C230` | `#F2C230` | Citations, active mode, focus |
| `--teal` | `#0E7C7B` | `#4FB7B5` | Local model, timestamps, links |
| `--plum` | `#6B4E9B` | `#B39AE0` | Cloud model |
| `--danger` | `#B42318` | `#FF8A80` | Errors |

- **Type scale:** 15px UI base; 17.5px serif for answers; 26–38px serif for the welcome headline. Tabular numerals for timestamps and latency.
- **Brand mark:** a small audio waveform in highlighter yellow, a nod to the podcast source.
- **Avoided on purpose:** cream and terracotta "AI" palettes, gradient washes, all-caps eyebrows, identical card grids.

## 3. Information architecture

```
┌ Rail (268px) ─────┬ Chat ───────────────────────────────┬ Artifact Viewer (≤720px) ─┐
│ Brand             │ Header: chat title · model dropdown │ Kind · title / picker   ✕ │
│ New chat          │                                     │ Preview | Source  Security│
│ Sessions (recent) │ Messages                            │                 Copy Down │
│   title · date    │   user bubble (right)               │                           │
│                   │   answer card: route · model · time │  sandboxed iframe or      │
│                   │     serif answer with ¹ ² chips     │  rendered Markdown        │
│                   │     [artifact card → Open in viewer]│                           │
│ Status            │     Show 6 transcript sources ▾     │                           │
│  ● 303 episodes   │ Composer: Auto Ask Essay Artifact   │                           │
│  ● Local: model   │   textarea                    Send  │                           │
│  ● Cloud: reason  │   hint for the selected mode        │                           │
└───────────────────┴─────────────────────────────────────┴───────────────────────────┘
```

- **Sessions** are the primary navigation; a new chat is one click and starts a fresh context.
- **Model choice belongs to the chat** (it is persisted per session), so it lives in the chat header, not in settings.
- **Health status** sits at the bottom of the rail: always visible and never in the way. It answers "is it my question or is the system down?"
- **Artifacts** live beside the conversation that produced them; earlier ones in the chat are reachable through the title picker and the cards in the thread.

## 4. Key interaction states

| State | What the user sees |
|---|---|
| Empty chat | Headline promise, one-line trust explanation, four starters labeled by mode |
| Thinking | Three-dot indicator inside the answer card (`aria-busy`) |
| Streaming | Text appears token by token; the citation list appears once complete |
| Essay or artifact in progress | The viewer opens at once with a waveform animation and a live character count; the chat says "Writing the artifact in the viewer" |
| Answer | Route label (Answer / Essay / Artifact), model badge (teal local, plum cloud), latency |
| Not in transcripts | Route label "Not in the transcripts" in red, plus suggested answerable questions |
| Degraded | Yellow notice inside the answer ("Semantic search unavailable; using keyword search only.", "fell back to ollama") |
| Error | Red card with the cause, the fix and Try again; request id for support |
| Artifact security | The Security button reveals what was removed and what the sandbox blocks |
| Stop | While streaming, Send becomes Stop (aborts the request) |

## 5. Responsive behaviour

| Width | Layout |
|---|---|
| > 1100px | Three columns: rail, chat, viewer |
| 760–1100px | Rail + chat; the viewer slides over from the right as a panel (max 640px) |
| < 760px | Chat only; the rail is a drawer (hamburger, scrim to close); the viewer is full screen; composer and type scale tighten |

Content width is capped at 760px for readable line length on wide screens. Tables in Markdown scroll horizontally rather than breaking the layout.

## 6. Accessibility

- Semantic landmarks: `nav` (chats), `main` (chat), `aside` (viewer); a skip link to the composer.
- Modes are a `radiogroup`; viewer tabs use `tablist` / `tab` with `aria-selected`; the source toggle uses `aria-expanded`.
- Streaming answers use `aria-live="polite"`; errors use `role="alert"`; status changes are announced.
- Citation chips are real buttons with descriptive labels ("Source 2: Annie Pearl at 00:34:38").
- A visible 3px highlighter focus ring on every interactive element; full keyboard use (Enter to send, Shift+Enter for a new line).
- Colour is never the only signal: status dots have text, routes have labels.
- Body text contrast meets WCAG AA in both themes; dark mode follows the OS.
- `prefers-reduced-motion` disables the waveform, typing dots and panel slide.

## 7. Design decisions and trade-offs

| Decision | Alternative | Why |
|---|---|---|
| Numbered citation chips + expandable source list | Footnotes only, or always-visible sources | Keeps answers scannable while making verification one click away |
| Deep link to the YouTube timestamp | Show the transcript only | Hearing the guest say it is the strongest trust signal |
| Explicit modes plus Auto | Auto only | Small models misread intent; modes give the user control and make the demo predictable |
| Viewer opens before generation finishes | Open on completion | Essays take 20–60s locally; immediate feedback reduces perceived latency |
| Serif for answers | One sans everywhere | Long-form reading comfort; separates content from chrome |
| Errors include the fix | Generic "something went wrong" | The users are technical; telling them `ollama pull qwen2.5:3b` saves a support ticket |
| No in-place artifact editing | Rich editor | Scope; copy and download cover v1, and regeneration via chat keeps grounding |
