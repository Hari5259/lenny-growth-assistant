# FAQ: design decisions and trade-offs

Short answers to the questions a reviewer is likely to ask. Longer reasoning is in [design.md](../design.md) and [architecture.md](../architecture.md).

### Why does the router use rules instead of letting the model choose a tool?
A 3B local model picks tools unreliably. Keyword rules ("write an essay", "one-pager", the mode buttons) are predictable, testable and cost nothing. The trade-off is that unusual phrasing falls back to Q&A, and the user can always pick the mode explicitly.

### Why hybrid search (vector + keyword) instead of vector only?
Vector search finds paraphrases ("retention" vs "churn"); keyword search finds exact names and terms ("Sean Ellis test", "PLG"). Reciprocal Rank Fusion merges both lists without tuning weights.

### How is "not covered" decided, and why 0.67?
If the best semantic match scores below `RETRIEVAL_MIN_VECTOR_SCORE`, the model is not called. 0.67 was not guessed: on the real index, answerable questions scored 0.70–0.79 and off-topic ones 0.51–0.64, so 0.67 sits in the gap. The first value (0.50) refused 0% of off-topic questions; after calibration it refused 100%, and hit@6 was 80%. The eval runner reproduces this.

### Why not let keyword hits rescue a weak semantic match?
That was the original rule, and it was the reason off-topic questions got through: common words like "point" matched many transcripts. Keyword counts now only matter when embeddings are unavailable.

### Doesn't refusing questions hurt usefulness?
Refusal is cheap and recoverable: the card offers suggested questions with one click. A confident wrong answer with a fake citation is expensive, because the user may put it in a strategy doc.

### Why `qwen2.5:3b` as the default?
It fits in the 4 GB VRAM of the target laptop's RTX 3050 together with the embedding model, and it streams fast enough for a demo. A 7B model does not fit and would spill to CPU. Switching is one line in `.env`.

### Why the Claude Agent SDK if the default model is local?
The SDK talks to Ollama through its Anthropic-compatible `/v1/messages` endpoint, so the same agent code serves local and cloud. If the SDK path fails before producing output, the request is retried on a plain HTTP engine and the answer carries a notice.

### How do you stop the model inventing citations?
Four layers: excerpts are numbered `[S1]…[Sn]` and the prompt says to cite or not claim; invalid ids are removed after generation; uncited essays get a Sources list appended but still count as uncited in the metric; the citation rate is reported at `/api/metrics`.

### Why is the HTML artifact sandbox so strict (no scripts at all)?
Generated HTML is untrusted output. It is sanitized on the server, given a restrictive CSP, and rendered in `<iframe sandbox="">`, which has an opaque origin and no script execution. Interactive artifacts would need a separate origin; that is out of scope for v1.

### What about prompt injection from transcripts?
Excerpts are wrapped as data in `<source>` tags, and the model has no dangerous tools: no shell, no file access, only a read-only search tool on the cloud path. The worst case is a bad answer, which the citations make visible.

### Why no authentication?
The brief describes an internal pilot. Each browser gets a user id stored with metadata, so adding SSO later means mapping that id to a real identity. It is the first item in the rollout plan in the PRD.

### What would you do next with more time?
A ~50-question eval set run in CI, cross-encoder re-ranking, ingesting the newsletter, SSO, and artifact versioning with share links.
