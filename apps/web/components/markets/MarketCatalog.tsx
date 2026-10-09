"use client";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { formatDate, formatNumber, formatPercent, numeric } from "@/lib/overview";
import { CompanyLogo } from "./CompanyLogo";
import type { Company, MarketOverview, MarketFreshness } from "@/lib/api";
import styles from "./markets.module.css";

export type MarketView = "index" | "stocks" | "sectors" | "events";
const views: Array<[MarketView, string, "market" | "company" | "grid" | "document"]> = [
  ["index", "Market digest", "market"], ["stocks", "All stocks", "company"], ["sectors", "Sectors", "grid"], ["events", "Events", "document"],
];

export function MarketCatalog({ view, select, market, freshness, companies, chart,onCompany }: {
  onCompany:(symbol:string)=>void; view: MarketView; select: (view: MarketView) => void; market: MarketOverview | null;
  freshness: MarketFreshness | null; companies: Company[]; chart: React.ReactNode;
}) {
  const snapshot = market?.snapshot;
  const bySymbol = new Map(companies.map(row => [row.symbol, row]));
  const watched = (market?.prices ?? market?.top_volume ?? []).slice().sort((a,b) => b.volume - a.volume).slice(0, 6);
  const percent = numeric(snapshot?.index_change_percent);
  return <aside data-workspace-left-panel className={styles.catalog} aria-label="Market navigation">

    {chart}
    <div className={styles.catalogList}><h2>Observed quotes <small>by volume</small></h2>{watched.map(row => <button key={row.symbol} onClick={()=>onCompany(row.symbol)}>
      <CompanyLogo symbol={row.symbol} website={bySymbol.get(row.symbol)?.official_website} size={24} /><strong>{row.symbol}</strong>
      <span className={styles.quotePrice}>{formatNumber(row.close)}</span><span className={Number(row.change_percent) < 0 ? styles.negative : styles.positive}>{formatPercent(row.change_percent)}</span>
    </button>)}{!watched.length ? <p className={styles.source}>Volume rankings unavailable.</p> : null}</div>
    <div className={styles.catalogCoverage}><span>Observed coverage</span><strong>{market?.priced_securities ?? "—"} <small>securities</small></strong>
      <p>{market?.sectors.length ?? "—"} sectors · {market?.price_basis === "intraday" ? "Intraday snapshot" : "Daily prices"}</p>
      <p className={freshness?.is_stale ? styles.negative : styles.muted}>{freshness?.is_stale ? "Data needs refresh" : freshness ? "Dated source observations" : "Freshness unavailable"}</p>
    </div>
  </aside>;
}
