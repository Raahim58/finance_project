"use client";
import Link from "next/link";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
import { AssistantControls } from "@/components/AssistantControls";
import { Icon } from "@/components/Icon";
import type { MarketOverview } from "@/lib/api";
import type { ResearchEventView } from "@/lib/api/research";
import { formatDate, formatNumber, formatPercent, humanize, numeric } from "@/lib/overview";
import { timeAgo } from "@/lib/markets";
import { CompanyLogo } from "./CompanyLogo";
import styles from "./markets.module.css";

export function MarketRail({ market, events, loading }: { market: MarketOverview | null; events: ResearchEventView[]; loading: boolean }) {
  const assistant = useAssistantWorkspace();
  const percent = numeric(market?.snapshot?.index_change_percent);
  const breadth = market?.sectors.reduce((total, row) => ({ up: total.up + row.advancers, down: total.down + row.decliners, flat: total.flat + row.unchanged }), { up: 0, down: 0, flat: 0 });
  const sectors = market?.sectors.slice().sort((a, b) => Number(b.average_change_percent) - Number(a.average_change_percent));
  const leader = sectors?.[0];
  // Repeated source/topic headlines do not occupy the whole contextual rail.
  const seen = new Set<string>();
  const evidence = events.filter(event => { const key = `${event.evidence[0]?.source_name}:${event.event_type}`; if (seen.has(key)) return false; seen.add(key); return true; }).slice(0, 3);
  const ask = (text: string) => assistant?.open(text);
  return <aside className={styles.rail} aria-label="Market context and Assistant">
    <div className={styles.railControls}><AssistantControls /></div><div className={styles.railHead}><h2>Market brief</h2><span>From market data</span></div>
    <section className={styles.digest}>
      <h3>{percent == null ? "Your market view, in context" : `KSE-100 ${percent < 0 ? "down" : percent > 0 ? "up" : "unchanged"}${percent === 0 ? "" : ` ${Math.abs(percent).toFixed(2)}%`}`}</h3>
      <p>{market ? `${market.priced_securities ?? "—"} securities across ${market.sectors.length} sectors are available in the ${market.price_basis === "intraday" ? "observed intraday snapshot" : "stored daily session"}.` : "The digest appears when a dated market snapshot is available."}</p>
      <p className={styles.time}>{formatDate(market?.trade_date)}{market?.observed_at ? ` · ${timeAgo(market.observed_at)}` : ""}</p>
      {breadth ? <div className={styles.breadth}><span><b className={styles.positive}>{breadth.up}</b> advancing</span><span><b className={styles.negative}>{breadth.down}</b> declining</span><span><b>{breadth.flat}</b> unchanged</span></div> : null}
      {(market?.top_gainers ?? []).slice(0, 3).length ? <div className={styles.tickerChips}>{market!.top_gainers.slice(0, 3).map(row => <Link href={`/companies/${row.symbol}` as never} key={row.symbol}><CompanyLogo symbol={row.symbol} size={18} /><span>{row.symbol}</span><b className={styles.positive}>{formatPercent(row.change_percent)}</b></Link>)}</div> : null}
    </section>
    {leader ? <section className={styles.railSection}><h3>Sector in focus</h3><p>{leader.sector}</p><strong className={Number(leader.average_change_percent) < 0 ? styles.negative : styles.positive}>{formatPercent(leader.average_change_percent)} <small>average quoted move</small></strong><p className={styles.source}>A simple average of observed stocks in the sector.</p></section> : null}
    <section className={styles.railSection}><div className={styles.railHead}><h3>Research evidence</h3><Link href="/research">View all <span aria-hidden="true">↗</span></Link></div>
      {evidence.map(event => <article className={styles.evidenceItem} key={event.event_key}>
        <span>{humanize(event.event_type)} · {formatDate(event.occurred_at)}</span><h4>{event.title}</h4>
        <div>{event.evidence[0]?.source_url ? <a href={event.evidence[0].source_url} target="_blank" rel="noreferrer">{event.evidence[0].source_name || event.evidence[0].title} <span aria-hidden="true">↗</span></a> : <span>Source link unavailable</span>}
          <button onClick={() => ask(`Explain this event using cited evidence: ${event.title}`)} aria-label={`Ask about ${event.title}`}><Icon name="assistant" size={14} /> Ask</button></div>
      </article>)}{!evidence.length ? <p className={styles.source}>{loading ? "Loading evidence…" : "No selected event evidence is available."}</p> : null}
    </section>
  </aside>;
}
