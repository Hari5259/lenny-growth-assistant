import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Source } from "../api";

/** Markdown renderer. Raw HTML is never rendered (react-markdown default), so model output
 *  cannot inject markup into the app. Citation ids like [S2] become timestamp chips. */
export function Markdown({ text, sources = [], onCite }: { text: string; sources?: Source[]; onCite?: (id: string) => void }) {
  const byId = new Map(sources.map((s) => [s.id, s]));
  const linked = text.replace(/\[(S\d+)\](?!\()/g, (m, id) => (byId.has(id) ? `[${id}](#cite-${id})` : m));
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a({ href, children }) {
          if (href?.startsWith("#cite-")) {
            const id = href.slice(6);
            const s = byId.get(id);
            const who = s?.guest ?? s?.speakers?.[0] ?? "Source";
            return (
              <button type="button" className="cite" onClick={() => onCite?.(id)}
                title={s ? `${s.episode_title}${s.start_ts ? " at " + s.start_ts : ""}` : id}
                aria-label={`Source ${id}: ${who}${s?.start_ts ? " at " + s.start_ts : ""}`}>
                {id.slice(1)}
              </button>
            );
          }
          return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
        },
      }}
    >
      {linked}
    </ReactMarkdown>
  );
}
