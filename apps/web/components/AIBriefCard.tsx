"use client";
import { useCallback, useEffect, useState } from "react";
import type { AIBriefView } from "@/lib/api/research";
import { formatDate } from "@/lib/overview";
import styles from "./ai-brief.module.css";

/** Cached AI brief. Opening a page only reads the cache; the server regenerates when its inputs change. */
export function AIBriefCard({ title, load }: { title: string; load: (retry: boolean) => Promise<AIBriefView> }) {
  const [view, setView] = useState<AIBriefView | null>(null);
  const [error, setError] = useState(false);
  const run = useCallback((retry = false) => load(retry).then(v => { setView(v); setError(false); return v; }).catch(() => { setError(true); return null; }), [load]);
  useEffect(() => {
    let live = true, tries = 0, timer: ReturnType<typeof setTimeout>;
    const tick = (retry = false) => run(retry).then(v => { if (live && v?.status === "generating" && tries++ < 15) timer = setTimeout(() => tick(), 5000); });
    void tick();
    return () => { live = false; clearTimeout(timer); };
  }, [run]);
  const brief = view?.brief;
  const note = error ? "Brief unavailable right now."
    : !view ? "Loading brief…"
    : view.status === "provider_unavailable" ? "Add an AI provider key in Settings to generate this brief."
    : view.status === "no_data" ? "No stored data to summarise yet."
    : view.status === "failed" ? "The last generation failed."
    : view.status === "generating" ? (brief ? "Refreshing — showing the previous brief." : "Preparing your brief…")
    : view.status === "not_generated" && !brief ? "Not generated yet." : null;
  const facts = new Map((view?.facts ?? []).map(f => [f.id, f]));
  return <section className={styles.card} aria-label={title}>
    <header><h2>{title}</h2>{view?.generated_at ? <small>AI summary of stored data · {formatDate(view.generated_at)}{view.current ? "" : " · out of date"}</small> : null}</header>
    {brief ? <>
      <p className={styles.headline}>{brief.headline}</p><p>{brief.summary}</p>
      <ul>{brief.points.map((p, i) => <li key={i}>{p.text} <span className={styles.refs}>{p.fact_ids.map(id => <abbr key={id} title={facts.get(id) ? `${facts.get(id)!.text} — ${facts.get(id)!.source}` : id}>[{id}]</abbr>)}</span></li>)}</ul>
      {brief.watch.length ? <p className={styles.watch}><b>Check:</b> {brief.watch.join(" · ")}</p> : null}
    </> : null}
    {note ? <p className={styles.note} role="status">{note}{view?.status === "failed" ? <button onClick={() => void run(true)}>Retry</button> : null}</p> : null}
  </section>;
}
