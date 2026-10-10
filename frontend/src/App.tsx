import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, streamMessage } from "./api";
import type { AppConfig, Artifact, Message, Mode, ProviderName, Readiness, Session } from "./api";
import { ArtifactViewer } from "./components/ArtifactViewer";
import { MessageView, type UiMessage } from "./components/MessageView";

const MODES: { id: Mode; label: string; help: string }[] = [
  { id: "auto", label: "Auto", help: "Detects whether you want an answer, an essay or an artifact" },
  { id: "qa", label: "Ask", help: "Short answer with sources" },
  { id: "essay", label: "Essay", help: "About 1,250 words in the Ship 30 for 30 style" },
  { id: "artifact", label: "Artifact", help: "A Markdown document or HTML page in the viewer" },
];

const STARTERS: { text: string; mode: Mode }[] = [
  { text: "How do the best teams know they have product-market fit?", mode: "qa" },
  { text: "What do guests say about pricing a B2B SaaS product?", mode: "qa" },
  { text: "Write an essay on building growth loops for a seed-stage PM", mode: "essay" },
  { text: "Make an HTML one-pager on running a great onboarding experiment", mode: "artifact" },
];

function getUserId(): string {
  try {
    let id = localStorage.getItem("lga.userId");
    if (!id) {
      id = "user-" + crypto.randomUUID().slice(0, 8);
      localStorage.setItem("lga.userId", id);
    }
    return id;
  } catch {
    return "guest";
  }
}

function toUi(m: Message, artifacts: Artifact[]): UiMessage {
  const art = m.artifact_id ? artifacts.find((a) => a.id === m.artifact_id) : null;
  return {
    id: m.id, role: m.role, content: m.content, route: m.route, provider: m.provider, model: m.model,
    sources: m.sources ?? [], notices: m.meta?.notices ?? [], artifactId: m.artifact_id, artifactTitle: art?.title,
    error: m.meta?.error ? { code: m.meta.error.code, message: m.meta.error.message } : null,
    latencyMs: m.meta?.latency_ms ?? null, firstTokenMs: m.meta?.timings?.first_token_ms ?? null,
    cited: m.meta?.cited,
  };
}

export default function App() {
  const userId = useRef(getUserId()).current;
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [ready, setReady] = useState<Readiness | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [current, setCurrent] = useState<Session | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [openArtifact, setOpenArtifact] = useState<Artifact | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [building, setBuilding] = useState<{ kind: string; chars: number } | null>(null);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [busy, setBusy] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const [bootError, setBootError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const lastPrompt = useRef<{ text: string; mode: Mode } | null>(null);

  const refreshStatus = useCallback(() => {
    api.config().then(setConfig).catch((e: ApiError) => setBootError(e.body?.hint ?? e.message));
    api.ready().then(setReady).catch(() => setReady(null));
  }, []);

  useEffect(() => {
    refreshStatus();
    api.listSessions(userId).then(setSessions).catch(() => {});
    const t = setInterval(refreshStatus, 30000);
    return () => clearInterval(t);
  }, [userId, refreshStatus]);

  useEffect(() => {
    if (messages.length === 0) { listRef.current?.scrollTo({ top: 0 }); return; }
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: busy ? "auto" : "smooth" });
  }, [messages, busy]);

  const provider: ProviderName = current?.provider ?? config?.default_provider ?? "ollama";
  const providerInfo = config?.providers.find((p) => p.name === provider);

  const loadSession = async (s: Session) => {
    abortRef.current?.abort();
    setDrawer(false);
    const d = await api.getSession(s.id);
    setCurrent(d);
    setArtifacts(d.artifacts);
    setMessages(d.messages.map((m) => toUi(m, d.artifacts)));
    setOpenArtifact(d.artifacts[0] ?? null);
    setViewerOpen(false);
  };

  const newChat = () => {
    abortRef.current?.abort();
    setCurrent(null);
    setMessages([]);
    setArtifacts([]);
    setOpenArtifact(null);
    setViewerOpen(false);
    setDrawer(false);
    inputRef.current?.focus();
  };

  const changeProvider = async (p: ProviderName) => {
    if (current) {
      const s = await api.updateSession(current.id, { provider: p });
      setCurrent(s);
      setSessions((xs) => xs.map((x) => (x.id === s.id ? s : x)));
    } else if (config) {
      setConfig({ ...config, default_provider: p });
    }
  };

  const removeSession = async (s: Session) => {
    if (!confirm(`Delete "${s.title}"? This removes its messages and artifacts.`)) return;
    await api.deleteSession(s.id);
    setSessions((xs) => xs.filter((x) => x.id !== s.id));
    if (current?.id === s.id) newChat();
  };

  const send = async (text: string, sendMode: Mode = mode) => {
    const content = text.trim();
    if (!content || busy) return;
    lastPrompt.current = { text: content, mode: sendMode };
    setInput("");
    setBusy(true);
    let session = current;
    try {
      if (!session) {
        session = await api.createSession(userId, null, provider);
        setCurrent(session);
        setSessions((xs) => [session!, ...xs]);
      }
    } catch (e) {
      const err = e instanceof ApiError ? e.body : { code: "ERROR", message: String(e) };
      setMessages((xs) => [...xs, { id: "u" + Date.now(), role: "user", content, sources: [] },
        { id: "e" + Date.now(), role: "assistant", content: "", sources: [], error: err }]);
      setBusy(false);
      return;
    }

    const aid = "a" + Date.now();
    setMessages((xs) => [...xs, { id: "u" + Date.now(), role: "user", content, sources: [] },
      { id: aid, role: "assistant", content: "", sources: [], streaming: true }]);
    const patch = (fn: (m: UiMessage) => UiMessage) => setMessages((xs) => xs.map((m) => (m.id === aid ? fn(m) : m)));

    const ctrl = new AbortController();
    abortRef.current = ctrl;
    let acc = "";
    try {
      await streamMessage(session.id, { content, mode: sendMode, provider: session.provider }, (ev) => {
        if (ev.type === "meta") {
          patch((m) => ({ ...m, route: ev.route, provider: ev.provider, model: ev.model, sources: ev.sources, notices: ev.notices }));
          if (ev.route === "essay" || ev.route === "artifact") { setViewerOpen(true); setOpenArtifact(null); setBuilding({ kind: ev.route === "essay" ? "markdown" : "html", chars: 0 }); }
        } else if (ev.type === "delta") {
          acc += ev.text;
          const at = acc.search(/<artifact\b/i);
          if (at !== -1) setBuilding((b) => ({ kind: /type="html"/i.test(acc.slice(at, at + 80)) ? "html" : b?.kind ?? "markdown", chars: acc.length - at }));
          patch((m) => ({ ...m, content: acc }));
        } else if (ev.type === "artifact") {
          setArtifacts((xs) => [ev.artifact, ...xs]);
          setOpenArtifact(ev.artifact);
          setViewerOpen(true);
          setBuilding(null);
          patch((m) => ({ ...m, artifactId: ev.artifact.id, artifactTitle: ev.artifact.title }));
        } else if (ev.type === "done") {
          const msg = ev.message;
          patch((m) => ({ ...m, id: msg.id, content: msg.content, sources: msg.sources, streaming: false,
            latencyMs: msg.meta?.latency_ms, firstTokenMs: msg.meta?.timings?.first_token_ms ?? null, notices: msg.meta?.notices ?? m.notices, route: msg.route ?? m.route }));
          setBuilding(null);
        } else if (ev.type === "error") {
          patch((m) => ({ ...m, streaming: false, error: ev.error }));
          setBuilding(null);
        }
      }, ctrl.signal);
    } catch (e) {
      const err = e instanceof ApiError ? e.body : { code: "ERROR", message: String(e) };
      patch((m) => ({ ...m, streaming: false, error: err }));
      setBuilding(null);
    } finally {
      patch((m) => (m.streaming ? { ...m, streaming: false } : m));
      setBusy(false);
      abortRef.current = null;
      const sid = session.id;
      api.listSessions(userId).then((xs) => {
        setSessions(xs);
        const fresh = xs.find((x) => x.id === sid);
        if (fresh) setCurrent((cur) => (cur?.id === sid ? { ...cur, title: fresh.title } : cur));
      }).catch(() => {});
      inputRef.current?.focus();
    }
  };

  const stop = () => abortRef.current?.abort();

  const kb = ready?.checks.knowledge_base;
  const viewerVisible = viewerOpen && (openArtifact || building);

  return (
    <div className={`shell${viewerVisible ? " with-viewer" : ""}`}>
      <a className="skip" href="#composer">Skip to message box</a>

      <nav className={`rail${drawer ? " open" : ""}`} aria-label="Chats">
        <div className="brand">
          <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" fill="var(--ink)" /><rect x="7" y="12" width="3" height="8" rx="1.5" fill="var(--hl)" /><rect x="12.5" y="8" width="3" height="16" rx="1.5" fill="var(--hl)" /><rect x="18" y="10" width="3" height="12" rx="1.5" fill="var(--hl)" /><rect x="23.5" y="13" width="3" height="6" rx="1.5" fill="var(--hl)" /></svg>
          <div>
            <p className="brand-name">Lenny Growth Assistant</p>
            <p className="brand-sub">Answers from Lenny's Podcast</p>
          </div>
        </div>
        <button className="new-chat" onClick={newChat}>New chat</button>
        <ul className="session-list">
          {sessions.length === 0 && <li className="empty-note">Your chats appear here.</li>}
          {sessions.map((s) => (
            <li key={s.id} className={current?.id === s.id ? "active" : undefined}>
              <button className="session-btn" onClick={() => loadSession(s)} aria-current={current?.id === s.id ? "page" : undefined}>
                <span className="session-title">{s.title}</span>
                <span className="session-date">{new Date(s.updated_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span>
              </button>
              <button className="icon-btn del" onClick={() => removeSession(s)} aria-label={`Delete chat ${s.title}`}>
                <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
              </button>
            </li>
          ))}
        </ul>
        <div className="status" aria-live="polite">
          {ready === null ? <p className="status-row bad">API not reachable</p> : (
            <>
              <p className={`status-row ${kb?.ok ? "ok" : "bad"}`}>
                {kb?.ok ? `${kb.episodes} episodes indexed` : "Transcripts not indexed yet"}
              </p>
              {kb && !kb.ok && kb.hint && <p className="status-hint">{kb.hint}</p>}
              {config?.providers.map((p) => (
                <p key={p.name} className={`status-row ${p.available ? "ok" : "bad"}`} title={p.reason ?? undefined}>
                  {p.local ? "Local" : "Cloud"}: {p.available ? p.model : p.reason}
                </p>
              ))}
            </>
          )}
        </div>
      </nav>
      {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}

      <main className="chat">
        <header className="chat-head">
          <button className="icon-btn menu" onClick={() => setDrawer(true)} aria-label="Open chats">
            <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h16M4 17h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
          </button>
          <h1 className="chat-title">{current?.title ?? "New chat"}</h1>
          <label className="provider">
            <span className="sr-only">Model</span>
            <select value={provider} onChange={(e) => changeProvider(e.target.value as ProviderName)} disabled={busy}
              className={providerInfo?.local ? "local" : "cloud"}>
              {config?.providers.map((p) => (
                <option key={p.name} value={p.name}>{p.local ? "Local" : "Cloud"}: {p.model}{p.available ? "" : " (unavailable)"}</option>
              )) ?? <option>Loading</option>}
            </select>
          </label>
          {artifacts.length > 0 && !viewerVisible && (
            <button className="text-btn" onClick={() => { setOpenArtifact(openArtifact ?? artifacts[0]); setViewerOpen(true); }}>
              Artifacts ({artifacts.length})
            </button>
          )}
        </header>

        <div className="messages" ref={listRef}>
          {bootError && <div className="error-box" role="alert"><p className="error-title">{bootError}</p></div>}
          {messages.length === 0 ? (
            <section className="welcome">
              <h2>Ask what Lenny's guests actually say about building and growing products.</h2>
              <p>Every answer cites the guest and the moment in the episode. If the transcripts don't cover something, the assistant says so instead of guessing.</p>
              <ul className="starters">
                {STARTERS.map((s) => (
                  <li key={s.text}>
                    <button onClick={() => send(s.text, s.mode)}>
                      <span className="starter-mode">{MODES.find((m) => m.id === s.mode)?.label}</span>
                      {s.text}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            messages.map((m, i) => (
              <MessageView key={m.id} m={m}
                onOpenArtifact={(id) => { const a = artifacts.find((x) => x.id === id); if (a) { setOpenArtifact(a); setViewerOpen(true); } }}
                onRetry={i === messages.length - 1 && lastPrompt.current ? () => send(lastPrompt.current!.text, lastPrompt.current!.mode) : undefined} />
            ))
          )}
        </div>

        <form id="composer" className="composer" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <div className="modes" role="radiogroup" aria-label="Response type">
            {MODES.map((m) => (
              <button key={m.id} type="button" role="radio" aria-checked={mode === m.id} title={m.help}
                className={mode === m.id ? "on" : undefined} onClick={() => setMode(m.id)}>{m.label}</button>
            ))}
          </div>
          <div className="input-row">
            <label htmlFor="msg" className="sr-only">Message</label>
            <textarea id="msg" ref={inputRef} rows={2} value={input} maxLength={4000}
              placeholder={mode === "essay" ? "Topic for the essay, e.g. retention for consumer apps" : mode === "artifact" ? "What should the document or page contain?" : "Ask about product, growth, hiring, pricing…"}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }} />
            {busy ? (
              <button type="button" className="send stop" onClick={stop}>Stop</button>
            ) : (
              <button type="submit" className="send" disabled={!input.trim()}>Send</button>
            )}
          </div>
          <p className="composer-hint">Enter to send, Shift+Enter for a new line. {MODES.find((m) => m.id === mode)?.help}.</p>
        </form>
      </main>

      {viewerVisible && (
        <ArtifactViewer artifact={openArtifact} artifacts={artifacts} building={openArtifact ? null : building}
          sources={messages.find((m) => m.artifactId && m.artifactId === openArtifact?.id)?.sources ?? []}
          onSelect={setOpenArtifact} onClose={() => setViewerOpen(false)} />
      )}
    </div>
  );
}
