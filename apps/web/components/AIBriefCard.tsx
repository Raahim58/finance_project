"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { CompanyLogo } from "@/components/markets/CompanyLogo";
import type { AIBriefView } from "@/lib/api/research";
import { formatDate, formatPercent } from "@/lib/overview";
import styles from "./ai-brief.module.css";

/** Cached AI brief. Opening a page only reads the cache; the server regenerates when its inputs change. */
type Fallback = { headline: string; summary: string };
export type BriefState = { view: AIBriefView | null; error: boolean; retry: () => void };
export type BriefProps = {
  title: string; state: BriefState;
  /** Database day-change percent by symbol; chips show the stored move for tickers the brief names. */
  quotes?: Record<string, number | null | undefined>;
  /** Deterministic headline and summary used until an AI brief exists. */
  fallback?: Fallback | null;
  onAsk?: (text: string) => void;
  /** Hide the "Market brief · date" line when the page already labels the block. */
  hideHeader?: boolean;
};

/** Loads the cached brief once; share the result between components that show parts of it. */
export function useBrief(load: (retry: boolean) => Promise<AIBriefView>): BriefState {
  const [view, setView] = useState<AIBriefView | null>(null);
  const [error, setError] = useState(false);
  const run = useCallback((retry = false) => load(retry).then(v => { setView(v); setError(false); return v; }).catch(() => { setError(true); return null; }), [load]);
  useEffect(() => {
    let live = true, tries = 0, timer: ReturnType<typeof setTimeout>;
    const tick = (retry = false) => run(retry).then(v => { if (live && v?.status === "generating" && tries++ < 15) timer = setTimeout(() => tick(), 5000); });
    void tick();
    return () => { live = false; clearTimeout(timer); };
  }, [run]);
  return { view, error, retry: () => void run(true) };
}

export function AIBriefCard({ title, state, quotes, fallback, onAsk, hideHeader }: BriefProps) {
  const { view, error } = state;
  const brief = view?.brief?.sections ? view.brief : null;
  const note = error ? "Brief unavailable right now."
    : !view ? "Loading brief…"
    : view.status === "provider_unavailable" ? "Add an AI provider key in Settings to generate this brief."
    : view.status === "no_data" ? "No stored data to summarise yet."
    : view.status === "failed" ? "The last generation failed."
    : view.status === "generating" ? (brief ? "Refreshing — showing the previous brief." : "Preparing your brief…")
    : view.status === "not_generated" && !brief ? "Not generated yet." : null;
  const facts = new Map((view?.facts ?? []).map(f => [f.id, f]));
  const headline = brief?.headline ?? fallback?.headline;
  return <section className={styles.card} aria-label={title}>
    {hideHeader ? null : <header><span className={styles.eyebrow}>{title}</span>{view?.generated_at ? <small>{formatDate(view.generated_at)}{view.current ? "" : " · out of date"}</small> : null}</header>}
    {headline ? <h2 className={styles.headline}>{headline}</h2> : null}
    {!brief && fallback?.summary ? <p className={styles.summary}>{fallback.summary}</p> : null}
    {brief ? brief.sections.map((sec, i) => <article className={styles.point} key={i}>
      {sec.title ? <h3>{sec.title}</h3> : null}
      <p>{sec.body} <span className={styles.refs}>{sec.fact_ids.map(id => <abbr key={id} title={facts.get(id) ? `${facts.get(id)!.text} — ${facts.get(id)!.source}` : id}>[{id}]</abbr>)}</span></p>
      {onAsk && sec.question ? <button className={styles.question} onClick={() => onAsk(`${sec.question} Use cited evidence: ${sec.body}`)}>{sec.question}</button> : null}
      {sec.tickers.length ? <div className={styles.chips}>{sec.tickers.map(symbol => { const change = quotes?.[symbol]; return <Link key={symbol} href={`/companies/${symbol}` as never}><CompanyLogo symbol={symbol} size={18} /><span>{symbol}</span>{change == null ? null : <b className={change < 0 ? styles.down : change > 0 ? styles.up : ""}>{formatPercent(change)}</b>}</Link>; })}</div> : null}
    </article>) : null}
    {brief?.events.length ? <div className={styles.watch}><h3>Upcoming Events</h3><ul>{brief.events.map((item, i) => <li key={i}>{item}</li>)}</ul></div> : null}
    {note ? <p className={styles.note} role="status">{note}{view?.status === "failed" ? <button onClick={state.retry}>Retry</button> : null}</p> : null}
  </section>;
}
