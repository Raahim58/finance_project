"use client";
import Link from "next/link";
import { useMemo } from "react";
import type { Company, MarketOverview, MarketPrice } from "@/lib/api";
import type { ResearchEventView } from "@/lib/api/research";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
import { formatDate, formatPercent, numeric } from "@/lib/overview";
import { CompanyLogo } from "./CompanyLogo";
import { AIBriefCard, type BriefState } from "@/components/AIBriefCard";
import styles from "./markets.module.css";

export function MarketDigest({ market, events, companies, brief, onStocks }: {
  market: MarketOverview | null; events: ResearchEventView[]; companies: Map<string, Company>; brief: BriefState; onStocks: () => void;
}) {
  const assistant = useAssistantWorkspace();
  const pct = numeric(market?.snapshot?.index_change_percent);
  const quotes = Array.from(new Map([...(market?.top_volume ?? []), ...(market?.top_gainers ?? [])].map(row => [row.symbol, row])).values());
  const chips = (rows: MarketPrice[]) => <div className={styles.digestChips}>{rows.map(row => <Link key={row.symbol} href={`/companies/${row.symbol}` as never}><CompanyLogo symbol={row.symbol} size={23} /><span>{row.symbol}</span><b className={Number(row.change_percent) < 0 ? styles.negative : styles.positive}>{formatPercent(row.change_percent)}</b></Link>)}</div>;
  const briefQuotes = useMemo(() => Object.fromEntries((market?.prices ?? [...(market?.top_gainers ?? []), ...(market?.top_losers ?? []), ...(market?.top_volume ?? [])]).map(row => [row.symbol, numeric(row.change_percent)])), [market]);
  const fallback = pct == null ? null : { headline: `KSE-100 ${pct < 0 ? "down" : pct > 0 ? "up" : "unchanged"}${pct === 0 ? "" : ` ${Math.abs(pct).toFixed(2)}%`}`, summary: "" };
  return <div className={styles.digestBody}>
    <AIBriefCard title="Market brief" state={brief} quotes={briefQuotes} fallback={fallback} onAsk={text => assistant?.open(text)} />
    <section><h2>The session in view</h2>
      <p>{market?.snapshot ? `KSE-100 ${market.price_basis === "intraday" ? "is observed" : "closed"} ${pct == null ? "with no reported change" : `${pct < 0 ? "down" : pct > 0 ? "up" : "unchanged"}${pct === 0 ? "" : ` ${Math.abs(pct).toFixed(2)}%`}`} on ${formatDate(market.trade_date)}. This view covers ${market.priced_securities ?? "—"} securities across ${market.sectors.length} sectors.` : "A dated session summary will appear when market data is available."}</p>
      <button className={styles.digestAction} onClick={onStocks}>› Explore the full market</button>
      {chips(quotes.slice(0, 3))}
    </section>
    <section><h2>Company evidence, in context</h2><p>Explore company filings, observed prices and recent events together. Each observation keeps its source date.</p>
      {quotes[0] ? <Link className={styles.digestAction} href={`/companies/${quotes[0].symbol}` as never}>› Show me the evidence for {quotes[0].symbol}</Link> : <Link className={styles.digestAction} href="/research">› Browse company research</Link>}
      {chips(quotes.slice(3, 6))}
    </section>
    <section><h2>What affects your portfolio?</h2><p>Review events against your actual holdings and confirmed IPS. Portfolio relevance uses the selected portfolio and cited evidence.</p>
      <button className={styles.digestAction} onClick={() => assistant?.open("Review the selected portfolio's exposure to recent market events using its actual holdings, confirmed IPS and current cited evidence. Identify missing inputs.")}>› Review my portfolio exposure</button>
    </section>
    <section className={styles.coverageNotes}><h2>Coverage notes</h2><p>{market ? `${market.price_basis === "intraday" ? "Hourly observed quotes" : "Stored daily closes"} are shown with their source dates. ${quotes.filter(row => !companies.has(row.symbol)).length ? "Some issuer profiles are missing. " : ""}Risk-free inputs and company fundamentals are assessed separately in the relevant analysis.` : "Market coverage is unavailable until a dated snapshot loads."}</p></section>
  </div>;
}
