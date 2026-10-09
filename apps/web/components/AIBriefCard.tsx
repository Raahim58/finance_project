"use client";
import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { CompanyLogo } from "@/components/markets/CompanyLogo";
import type { AIBriefView } from "@/lib/api/research";
import { formatDate, formatPercent } from "@/lib/overview";
import styles from "./ai-brief.module.css";

/** Cached AI brief. Opening a page only reads the cache; the server regenerates when its inputs change. */
const SYMBOL = /\b[A-Z][A-Z0-9]{1,9}\b/g;
type Fallback = { headline: string; summary: string };
export type BriefProps = {
  title: string; load: (retry: boolean) => Promise<AIBriefView>;
  /** Database day-change percent by symbol; chips appear only for symbols named in the brief text. */
  quotes?: Record<string, number | null | undefined>;
  /** Deterministic, database-derived lead shown under the headline (index move, breadth, benchmark). */
  lead?: ReactNode;
  /** Deterministic headline and summary used until an AI brief exists. */
  fallback?: Fallback | null;
  /** Label and handler for the follow-up question under each point. */
  question?: string; onAsk?: (text: string) => void;
};

export function AIBriefCard({ title, load, quotes, lead, fallback, question = "Why does this matter?", onAsk }: BriefProps) {
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
  const chips = (text: string) => Array.from(new Set(text.match(SYMBOL) ?? [])).filter(symbol => quotes && symbol in quotes).slice(0, 4);
  const headline = brief?.headline ?? fallback?.headline, summary = brief?.summary ?? fallback?.summary;
  return <section className={styles.card} aria-label={title}>
    <header><span className={styles.eyebrow}>{title}</span>{view?.generated_at ? <small>AI summary of stored data · {formatDate(view.generated_at)}{view.current ? "" : " · out of date"}</small> : null}</header>
    {headline ? <h2 className={styles.headline}>{headline}</h2> : null}
    {summary ? <p className={styles.summary}>{summary}</p> : null}
    {lead ? <div className={styles.lead}>{lead}</div> : null}
    {brief ? brief.points.map((p, i) => <article className={styles.point} key={i}>
      <p>{p.text} <span className={styles.refs}>{p.fact_ids.map(id => <abbr key={id} title={facts.get(id) ? `${facts.get(id)!.text} — ${facts.get(id)!.source}` : id}>[{id}]</abbr>)}</span></p>
      {onAsk ? <button className={styles.question} onClick={() => onAsk(`${question} Use cited evidence: ${p.text}`)}>{question}</button> : null}
      {chips(p.text).length ? <div className={styles.chips}>{chips(p.text).map(symbol => { const change = quotes![symbol]; return <Link key={symbol} href={`/companies/${symbol}` as never}><CompanyLogo symbol={symbol} size={18} /><span>{symbol}</span>{change == null ? null : <b className={change < 0 ? styles.down : change > 0 ? styles.up : ""}>{formatPercent(change)}</b>}</Link>; })}</div> : null}
    </article>) : null}
    {brief?.watch.length ? <div className={styles.watch}><h3>Worth checking</h3><ul>{brief.watch.map((item, i) => <li key={i}>{item}</li>)}</ul></div> : null}
    {note ? <p className={styles.note} role="status">{note}{view?.status === "failed" ? <button onClick={() => void run(true)}>Retry</button> : null}</p> : null}
  </section>;
}
