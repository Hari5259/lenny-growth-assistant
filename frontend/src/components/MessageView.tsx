import { useState } from "react";
import type { ApiErrorBody, Source } from "../api";
import { Markdown } from "./Markdown";

export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  route?: string | null;
  provider?: string | null;
  model?: string | null;
  sources: Source[];
  notices?: string[];
  artifactId?: string | null;
  artifactTitle?: string | null;
  streaming?: boolean;
  error?: ApiErrorBody | null;
  latencyMs?: number | null;
  firstTokenMs?: number | null;
  cited?: boolean;
}

const ROUTE_LABEL: Record<string, string> = {
  qa: "Answer", essay: "Essay", artifact: "Artifact", no_answer: "Not in the transcripts",
};

function stripArtifact(text: string): { visible: string; building: boolean } {
  const i = text.search(/<artifact\b/i);
  if (i === -1) return { visible: text, building: false };
  return { visible: text.slice(0, i).trim(), building: !/<\/artifact>/i.test(text) };
}

const SUGGESTIONS = [
  "How do the best companies measure product-market fit?",
  "What do guests say about pricing a B2B SaaS product?",
  "How should a PM prioritise a roadmap?",
];

export function MessageView({ m, onOpenArtifact, onRetry, onAsk }: {
  m: UiMessage;
  onOpenArtifact: (id: string) => void;
  onRetry?: () => void;
  onAsk?: (text: string) => void;
}) {
  const [openSources, setOpenSources] = useState(false);
  const [focused, setFocused] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  if (m.role === "user") {
    return <div className="msg msg-user"><p>{m.content}</p></div>;
  }

  const { visible, building } = m.streaming ? stripArtifact(m.content) : { visible: m.content, building: false };
  const cite = (id: string) => {
    setOpenSources(true);
    setFocused(id);
    requestAnimationFrame(() => document.getElementById(`${m.id}-${id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  };

  return (
    <div className={`msg msg-assistant${m.error ? " msg-error" : ""}`}>
      {m.route && !m.error && (
        <div className="msg-meta">
          <span className={`route route-${m.route}`}>{ROUTE_LABEL[m.route] ?? m.route}</span>
          {m.provider && <span className={`prov ${m.provider === "ollama" ? "prov-local" : "prov-cloud"}`}>{m.provider === "ollama" ? "Local" : "Cloud"} {m.model}</span>}
          {m.latencyMs != null && (
            <span className="latency" title="Total time for this answer">{(m.latencyMs / 1000).toFixed(1)}s total</span>
          )}
          {m.firstTokenMs != null && (
            <span className="latency" title="Time until the model wrote its first word">
              first word {(m.firstTokenMs / 1000).toFixed(1)}s
            </span>
          )}
        </div>
      )}

      {m.notices?.map((n) => <p key={n} className="notice" role="note">{n}</p>)}

      {m.error ? (
        <div className="error-box" role="alert">
          <p className="error-title">{m.error.message}</p>
          {m.error.hint && <p className="error-hint">{m.error.hint}</p>}
          <div className="error-actions">
            {onRetry && <button className="text-btn" onClick={onRetry}>Try again</button>}
            {m.error.request_id && <span className="rid">Request {m.error.request_id}</span>}
          </div>
        </div>
      ) : (
        m.route === "no_answer" && !m.streaming && onAsk ? (
          <div className="prose answer">
            <p>{m.content.split("\n\n")[0]}</p>
            <p className="suggest-label">Try one of these instead:</p>
            <div className="suggestions">
              {SUGGESTIONS.map((q) => (
                <button key={q} className="suggestion" onClick={() => onAsk(q)}>{q}</button>
              ))}
            </div>
          </div>
        ) : (
        <div className="prose answer" aria-live={m.streaming ? "polite" : undefined} aria-busy={m.streaming}>
          {visible ? <Markdown text={visible} sources={m.sources} onCite={cite} /> : m.streaming && !building ? <span className="typing" aria-label="Thinking"><i /><i /><i /></span> : null}
          {building && <p className="building-inline">Writing the artifact in the viewer.</p>}
        </div>
        )
      )}

      {m.artifactId && (
        <button className="artifact-card" onClick={() => onOpenArtifact(m.artifactId!)}>
          <span className="artifact-card-title">{m.artifactTitle ?? "Artifact"}</span>
          <span className="artifact-card-cta">Open in viewer</span>
        </button>
      )}

      {!m.streaming && !m.error && m.content && (
        <div className="msg-actions">
          <button className="text-btn" onClick={async () => {
            try {
              await navigator.clipboard.writeText(m.content);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            } catch { /* clipboard blocked: nothing to do */ }
          }}>{copied ? "Copied" : "Copy answer"}</button>
        </div>
      )}

      {m.sources.length > 0 && !m.streaming && (
        <div className="sources">
          <button className="sources-toggle" aria-expanded={openSources} onClick={() => setOpenSources((v) => !v)}>
            {openSources ? "Hide" : "Show"} {m.sources.length} transcript source{m.sources.length > 1 ? "s" : ""}
          </button>
          {openSources && (
            <ol className="source-list">
              {m.sources.map((s) => (
                <li key={s.id} id={`${m.id}-${s.id}`} className={focused === s.id ? "focused" : undefined}>
                  <div className="source-head">
                    <span className="source-id">{s.id.slice(1)}</span>
                    <span className="source-who">{s.guest ?? s.speakers[0]}</span>
                    {s.deep_link ? (
                      <a className="stamp" href={s.deep_link} target="_blank" rel="noopener noreferrer"
                        aria-label={`Watch at ${s.start_ts} on YouTube`}>{s.start_ts ?? "0:00"}</a>
                    ) : <span className="stamp">{s.start_ts}</span>}
                  </div>
                  <p className="source-ep">{s.episode_title}</p>
                  <blockquote>{s.snippet}</blockquote>
                  <a className="source-file" href={s.source_url} target="_blank" rel="noopener noreferrer">Transcript file</a>
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </div>
  );
}
