"use client";
import Link from "next/link";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
import type { BriefState } from "@/components/AIBriefCard";
import { Icon } from "@/components/Icon";
import type { MarketOverview } from "@/lib/api";
import type { ResearchEventView } from "@/lib/api/research";
import { formatDate, formatPercent, humanize, numeric } from "@/lib/overview";
import { CompanyLogo } from "./CompanyLogo";
import styles from "./markets.module.css";

export function MarketRail({ market, events, loading, brief, onSector }: {brief: BriefState;onSector?:(sector:string)=>void; market: MarketOverview | null; events: ResearchEventView[]; loading: boolean }) {
  const assistant = useAssistantWorkspace();
  const percent = numeric(market?.snapshot?.index_change_percent);
  const breadth = market?.sectors.reduce((total, row) => ({ up: total.up + row.advancers, down: total.down + row.decliners, flat: total.flat + row.unchanged }), { up: 0, down: 0, flat: 0 });
  const sectors = market?.sectors.slice().sort((a, b) => Number(b.average_change_percent) - Number(a.average_change_percent));
  const leader = sectors?.[0];
  // Repeated source/topic headlines do not occupy the whole contextual rail.
  const seen = new Set<string>();
  const evidence = events.filter(event => { const key = `${event.evidence[0]?.source_name}:${event.event_type}`; if (seen.has(key)) return false; seen.add(key); return true; }).slice(0, 3);
  const ask = (text: string) => assistant?.open(text);
  const summary = brief.view?.brief?.summary || null;
  return <aside className={styles.rail} aria-label="Market context and Assistant">
    {summary ? <p className={styles.railSummary}>{summary}</p> : null}
    {leader ? <section className={styles.railSection}><h3>Sector in focus</h3><p>{onSector?<button onClick={()=>onSector(leader.sector)}>{leader.sector} ›</button>:leader.sector}</p><strong className={Number(leader.average_change_percent) < 0 ? styles.negative : styles.positive}>{formatPercent(leader.average_change_percent)} <small>average quoted move</small></strong><p className={styles.source}>A simple average of observed stocks in the sector.</p></section> : null}
    <section className={styles.railSection}><div className={styles.railHead}><h3>Research evidence</h3><Link href="/research">View all <span aria-hidden="true">↗</span></Link></div>
      {evidence.map(event => <article className={styles.evidenceItem} key={event.event_key}>
        <span>{humanize(event.event_type)} · {formatDate(event.occurred_at)}</span><h4>{event.evidence[0]?.title || event.title}</h4>{event.evidence[0]?.title && event.evidence[0].title!==event.title ? <blockquote className={styles.excerpt}>{event.title}</blockquote>:null}
        <div>{event.evidence[0]?.source_url ? <a href={event.evidence[0].source_url} target="_blank" rel="noreferrer">{event.evidence[0].source_name || event.evidence[0].title} <span aria-hidden="true">↗</span></a> : <span>Source link unavailable</span>}
          <button onClick={() => ask(`Explain this event using cited evidence: ${event.title}`)} aria-label={`Ask about ${event.title}`}><Icon name="assistant" size={14} /> Ask</button></div>
      </article>)}{!evidence.length ? <p className={styles.source}>{loading ? "Loading evidence…" : "No selected event evidence is available."}</p> : null}
    </section>
  </aside>;
}
