"use client";

import Link from "next/link";
import type { PortfolioSummary } from "@/lib/api";
import { CompanyLogo } from "@/components/markets/CompanyLogo";
import { formatDate, formatNumber, formatPercent, numeric } from "@/lib/overview";
import s from "./quant.module.css";

export function QuantPortfolioRail({ summary, portfolioId, loading }: { summary: PortfolioSummary | null; portfolioId: string; loading: boolean }) {
  const total = numeric(summary?.total_value);
  const cash = numeric(summary?.cash_balance);
  // Weights require a complete valuation. Unpriced holdings cannot silently become zero weights.
  const complete = summary?.valuation_complete === true && total != null && total > 0;
  const cashWeight = complete && cash != null ? cash / total : null;
  const change = numeric(summary?.day_change_percent);
  const holdings = [...(summary?.holdings ?? [])].sort((a, b) => (numeric(b.market_value) ?? -Infinity) - (numeric(a.market_value) ?? -Infinity));
  return <aside className={s.portfolioRail} aria-label="Selected portfolio">
    {!summary ? <p className={s.eyebrow}>{loading ? "Loading portfolio…" : "Portfolio unavailable"}</p> : null}
    <p className={s.eyebrow}>Portfolio value</p>
    <strong className={s.portfolioValue}>{total == null ? "—" : `${summary?.portfolio.base_currency ?? "PKR"} ${formatNumber(total, 0)}`}</strong>
    <p className={change == null ? s.eyebrow : change < 0 ? s.negative : change > 0 ? s.positive : s.eyebrow}>{formatPercent(change)} · {formatDate(summary?.data_freshness_date)}</p>
    <span className={s.eyebrow}>{summary?.valuation_complete ? "Latest stored valuation" : "Valuation incomplete"}</span>
    {summary?.valuation_note ? <p className={s.readonly}>{summary.valuation_note}</p> : null}
    <section className={s.cashSection}><span>Cash</span><span className={s.cashRing} style={{ background: cashWeight == null ? "#eef0f3" : `conic-gradient(#00a785 ${Math.max(0, Math.min(1, cashWeight)) * 360}deg, #eef0f3 0deg)` }} aria-hidden="true" /><div><strong>{cashWeight == null ? "—" : `${(cashWeight * 100).toFixed(2)}%`}</strong><small>of portfolio</small></div></section>
    <section className={s.holdingSection}><h3>PSX holdings</h3>{holdings.length ? <ul className={s.holdings}>{holdings.map(holding => { const value = numeric(holding.market_value); const weight = complete && holding.latest_price != null && value != null ? value / total : null; return <li key={holding.holding_id}><Link href={`/companies/${holding.symbol}` as never}><CompanyLogo symbol={holding.symbol} size={28} /><span>{holding.symbol}</span><b>{weight == null ? "—" : `${(weight * 100).toFixed(2)}%`}</b></Link></li>; })}</ul> : <p className={s.readonly}>{loading ? "Loading holdings…" : "No holdings available."}</p>}<Link className={s.seeAll} href={`/portfolios/${portfolioId}/overview` as never}>See all holdings →</Link></section>
  </aside>;
}
