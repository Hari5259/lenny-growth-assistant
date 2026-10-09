import { useEffect, useRef, useState } from "react";
import type { Artifact, Source } from "../api";
import { Markdown } from "./Markdown";

interface Props {
  artifact: Artifact | null;
  artifacts: Artifact[];
  building: { kind: string; chars: number } | null;
  sources: Source[];
  onSelect: (a: Artifact) => void;
  onClose: () => void;
}

/** Renders generated artifacts beside the chat.
 *  HTML: <iframe sandbox=""> + srcdoc. The empty sandbox means no scripts, no forms, no popups,
 *  no top navigation and an opaque origin (no access to this app's DOM, cookies or storage).
 *  The server has already stripped active content and injected a strict CSP.
 *  Markdown: rendered as React elements; raw HTML inside markdown is ignored. */
export function ArtifactViewer({ artifact, artifacts, building, sources, onSelect, onClose }: Props) {
  const [tab, setTab] = useState<"preview" | "source">("preview");
  const [copied, setCopied] = useState(false);
  const [showPolicy, setShowPolicy] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => { setTab("preview"); setShowPolicy(false); }, [artifact?.id]);
  useEffect(() => { closeRef.current?.focus(); }, []);

  const copy = async () => {
    if (!artifact) return;
    await navigator.clipboard.writeText(artifact.content);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  const download = () => {
    if (!artifact) return;
    const ext = artifact.kind === "html" ? "html" : "md";
    const blob = new Blob([artifact.content], { type: artifact.kind === "html" ? "text/html" : "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${artifact.title.replace(/[^\w\- ]+/g, "").trim().replace(/\s+/g, "-").toLowerCase() || "artifact"}.${ext}`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  const removed = artifact?.sanitizer?.removed_tags ? Object.entries(artifact.sanitizer.removed_tags as Record<string, number>) : [];

  return (
    <aside className="viewer" aria-label="Artifact viewer">
      <header className="viewer-head">
        <div className="viewer-title">
          <span className={`kind kind-${artifact?.kind ?? building?.kind ?? "markdown"}`}>
            {(artifact?.kind ?? building?.kind) === "html" ? "HTML" : "Markdown"}
          </span>
          {artifacts.length > 1 ? (
            <select aria-label="Choose artifact" value={artifact?.id ?? ""}
              onChange={(e) => { const a = artifacts.find((x) => x.id === e.target.value); if (a) onSelect(a); }}>
              {artifacts.map((a) => <option key={a.id} value={a.id}>{a.title}</option>)}
            </select>
          ) : (
            <h2>{artifact?.title ?? "Building artifact"}</h2>
          )}
        </div>
        <button ref={closeRef} className="icon-btn" onClick={onClose} aria-label="Close artifact viewer">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
        </button>
      </header>

      {artifact && (
        <div className="viewer-bar">
          <div className="tabs" role="tablist" aria-label="View">
            <button role="tab" aria-selected={tab === "preview"} onClick={() => setTab("preview")}>Preview</button>
            <button role="tab" aria-selected={tab === "source"} onClick={() => setTab("source")}>Source</button>
          </div>
          <div className="viewer-actions">
            {artifact.kind === "html" && (
              <button className="text-btn" aria-expanded={showPolicy} onClick={() => setShowPolicy((v) => !v)}>Security</button>
            )}
            <button className="text-btn" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
            <button className="text-btn" onClick={download}>Download</button>
          </div>
        </div>
      )}

      {showPolicy && artifact && (
        <div className="policy" role="note">
          <p><strong>Rendered in a locked sandbox.</strong> Scripts, forms, pop-ups, network requests and access to this app are blocked. Only inline CSS and embedded images are allowed.</p>
          <p>{removed.length ? `Removed before display: ${removed.map(([t, n]) => `${n} ${t}`).join(", ")}.` : "Nothing needed removing."}
            {artifact.sanitizer?.removed_attrs ? ` ${artifact.sanitizer.removed_attrs} event handler(s) stripped.` : ""}
            {artifact.sanitizer?.removed_urls ? ` ${artifact.sanitizer.removed_urls} external link(s) or URL(s) stripped.` : ""}</p>
        </div>
      )}

      <div className="viewer-body">
        {!artifact && building && (
          <div className="building" role="status">
            <div className="wave" aria-hidden="true"><span /><span /><span /><span /><span /></div>
            <p>Writing the artifact. {building.chars.toLocaleString()} characters so far.</p>
          </div>
        )}
        {artifact && tab === "source" && <pre className="source"><code>{artifact.content}</code></pre>}
        {artifact && tab === "preview" && artifact.kind === "html" && (
          <iframe title={artifact.title} sandbox="" srcDoc={artifact.content} referrerPolicy="no-referrer" className="frame" />
        )}
        {artifact && tab === "preview" && artifact.kind === "markdown" && (
          <article className="doc prose"><Markdown text={artifact.content} sources={sources}
            onCite={(id) => { const s = sources.find((x) => x.id === id); if (s?.deep_link) window.open(s.deep_link, "_blank", "noopener"); }} /></article>
        )}
      </div>
    </aside>
  );
}
