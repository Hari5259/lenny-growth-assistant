import { useEffect, useRef } from "react";

/** Plain-language explanation of what the assistant does and how far to trust it. */
export function AboutDialog({ open, onClose, episodes }: { open: boolean; onClose: () => void; episodes?: number }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog ref={ref} className="about" onClose={onClose} aria-labelledby="about-title">
      <header className="about-head">
        <h2 id="about-title">How this assistant works</h2>
        <button className="icon-btn" onClick={onClose} aria-label="Close">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
        </button>
      </header>
      <div className="about-body">
        <h3>Where answers come from</h3>
        <p>
          Only from the transcripts of Lenny's Podcast{episodes ? ` (${episodes} episodes indexed)` : ""}.
          For each question it finds the most relevant moments, and the AI answers from those excerpts alone.
        </p>
        <h3>How to check an answer</h3>
        <p>
          The yellow numbers are sources. Click one to see the guest, the episode, the exact quote, and a
          link that opens YouTube at that minute.
        </p>
        <h3>When it says "not covered"</h3>
        <p>
          If no transcript is close enough to your question, it says so and does not call the AI at all.
          That is deliberate: no answer is better than an invented one.
        </p>
        <h3>Local or cloud</h3>
        <p>
          <strong>Local</strong> runs the AI on this computer through Ollama: nothing leaves the machine.
          <strong> Cloud</strong> uses Claude for better writing, if an API key is configured. The model
          used is shown on every answer.
        </p>
        <h3>Essays and documents</h3>
        <p>
          <strong>Essay</strong> writes a long-form post in the Ship 30 for 30 style. <strong>Artifact</strong> makes
          a Markdown document or a web page. Both open on the right, where you can copy or download them.
          Generated web pages run in a locked sandbox: no scripts, no network, no access to this app.
        </p>
      </div>
    </dialog>
  );
}
