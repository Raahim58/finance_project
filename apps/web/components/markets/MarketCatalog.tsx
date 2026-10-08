"use client";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { formatDate, formatNumber, formatPercent, numeric } from "@/lib/overview";
import { CompanyLogo } from "./CompanyLogo";
import type { Company, MarketOverview, MarketFreshness } from "@/lib/api";
import styles from "./markets.module.css";

export type MarketView = "index" | "stocks" | "sectors";
const views: Array<[MarketView, string, "market" | "company" | "grid"]> = [
  ["index", "KSE-100", "market"], ["stocks", "All stocks", "company"], ["sectors", "Sectors", "grid"],
];

export function MarketCatalog({ view, select, market, freshness, companies }: {
  view: MarketView; select: (view: MarketView) => void; market: MarketOverview | null;
  freshness: MarketFreshness | null; companies: Company[];
}) {
  const snapshot = market?.snapshot;
  const bySymbol = new Map(companies.map(row => [row.symbol, row]));
  const watched = (market?.top_volume ?? []).slice(0, 5);
  const percent = numeric(snapshot?.index_change_percent);
  return <aside className={styles.catalog} aria-label="Market navigation">
    <div className={styles.catalogHeading}><strong>Markets</strong><span>PSX</span></div>
    <div className={styles.catalogQuote}>
      <span>KSE-100</span><strong>{formatNumber(snapshot?.index_value)}</strong>
      <p className={percent != null && percent < 0 ? styles.negative : styles.positive}>{snapshot ? formatPercent(percent) : "Observation unavailable"}</p>
      <small>{formatDate(snapshot?.snapshot_date ?? market?.trade_date)}</small>
    </div>
    <nav className={styles.catalogViews} aria-label="Market views">{views.map(([key, label, icon]) =>
      <button key={key} aria-current={view === key ? "page" : undefined} onClick={() => select(key)}><Icon name={icon} size={17} /><span>{label}</span><Icon name="chevron" size={13} /></button>)}</nav>
    <div className={styles.catalogList}><h2>Most active</h2>{watched.map(row => <Link key={row.symbol} href={`/companies/${row.symbol}` as never}>
      <CompanyLogo symbol={row.symbol} website={bySymbol.get(row.symbol)?.official_website} size={24} /><strong>{row.symbol}</strong>
      <span className={Number(row.change_percent) < 0 ? styles.negative : styles.positive}>{formatPercent(row.change_percent)}</span>
    </Link>)}{!watched.length ? <p className={styles.source}>Volume rankings unavailable.</p> : null}</div>
    <div className={styles.catalogCoverage}><span>Observed coverage</span><strong>{market?.priced_securities ?? "—"} <small>securities</small></strong>
      <p>{market?.sectors.length ?? "—"} sectors · {market?.price_basis === "intraday" ? "Intraday snapshot" : "Daily prices"}</p>
      <p className={freshness?.is_stale ? styles.negative : styles.muted}>{freshness?.is_stale ? "Data needs refresh" : freshness ? "Dated source observations" : "Freshness unavailable"}</p>
    </div>
  </aside>;
}
