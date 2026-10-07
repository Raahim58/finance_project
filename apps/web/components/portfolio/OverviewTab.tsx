"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { CompanyLogo } from "@/components/markets/CompanyLogo";
import { IndexChart } from "@/components/markets/IndexChart";
import { SparkPath } from "@/components/markets/Sparkline";
import type { WorkspaceData } from "@/components/workspace/useWorkspaceData";
import { indexLatest, timeAgo } from "@/lib/markets";
import { formatDate, formatNumber, formatPercent, humanize, numeric } from "@/lib/overview";
import { activityLine, briefHeadline, holdingRows, movers, overviewRanges, rangeSlice, valuePoints, type HoldingRow, type OverviewRange } from "@/lib/portfolio-overview";
import { useOverviewExtras } from "./overview/useOverviewExtras";
import styles from "./overview/overview.module.css";

const tone = (value: number | null) => value == null || value === 0 ? "" : value > 0 ? styles.positive : styles.negative;
const pkr = (value: number | null, signed = false) => value == null ? "—" : `${signed ? (value > 0 ? "+" : value < 0 ? "−" : "") : value < 0 ? "−" : ""}PKR ${formatNumber(Math.abs(value), 0)}`;

export function OverviewTab({ portfolioId, data }: { portfolioId: string; data: WorkspaceData; setMessage: (message: string) => void }) {
  const { summary } = data;
  const symbols = useMemo(() => summary?.holdings.map(holding => holding.symbol) ?? [], [summary]);
  const extras = useOverviewExtras(portfolioId, symbols);
  const [range, setRange] = useState<OverviewRange>("3M");
  const [query, setQuery] = useState("");
  const rows = useMemo(() => summary ? holdingRows(summary, extras.history) : [], [summary, extras.history]);
  const points = useMemo(() => valuePoints(data.performance), [data.performance]);
  if (!summary) return <p className={styles.empty}>Portfolio summary unavailable. The API did not return a database valuation.</p>;

  const total = numeric(summary.total_value), cash = numeric(summary.cash_balance), dayChange = numeric(summary.day_change), dayPercent = numeric(summary.day_change_percent);
  const gain = numeric(summary.unrealized_gain_loss), gainPercent = numeric(summary.unrealized_gain_loss_percent);
  const invested = total != null && cash != null ? total - cash : null;
  const share = (part: number | null) => part != null && total ? `${(part / total * 100).toFixed(1)}% of value` : "";
  const quant = data.quant?.portfolio as Record<string, unknown> | undefined;
  const quantOk = quant && quant.available !== false;
  const cagr = quantOk ? numeric(quant.realized_cagr) : null, vol = quantOk ? numeric(quant.annual_volatility) : null;
  const benchmark = indexLatest(extras.index.value ?? [], null);
  const brief = briefHeadline(summary.portfolio.name, dayPercent, dayChange, benchmark && { name: benchmark.name, percent: benchmark.percent });
  const { contributors, detractors } = movers(rows);
  const shown = rows.filter(row => `${row.symbol} ${row.name} ${row.sector}`.toLowerCase().includes(query.trim().toLowerCase()));
  const chartPoints = rangeSlice(points, range);
  const compliance = data.compliance, status = compliance?.status ?? (compliance ? (compliance.compliant ? "PASS" : "BREACH") : null);
  const notices = [
    summary.valuation_complete ? null : `Valuation incomplete${summary.unpriced_symbols.length ? `: no stored price for ${summary.unpriced_symbols.join(", ")}` : ""}. Totals exclude unpriced holdings.`,
    summary.valuation_note,
  ].filter(Boolean);

  return <div className={styles.layout}>
    <div className={styles.main}>
      <div className={`${styles.notice} ${status === "BREACH" ? styles.bad : status === "PASS" && !notices.length ? styles.ok : ""}`} role="status">
        <span><b>Mandate:</b> {status === "PASS" ? "Within IPS limits" : status === "BREACH" ? `IPS breach${compliance?.violations.length ? ` (${compliance.violations.length})` : ""}` : status === "NOT_EVALUATED" ? "Not evaluated (IPS data missing)" : "Compliance unavailable"}</span>
        <span><b>Prices:</b> {summary.data_freshness_date ? `as of ${formatDate(summary.data_freshness_date)}` : "date unavailable"} · {summary.data_source ?? "source unavailable"}</span>
        {notices.map(note => <span key={note}>{note}</span>)}
      </div>

      <section>
        <div className={styles.heroTop}>
          <div>
            <span className={styles.level}>{pkr(total)}</span>
            <p className={`${styles.change} ${tone(dayChange)}`}>{pkr(dayChange, true)} {formatPercent(dayPercent)} <span>latest session · daily data only</span></p>
          </div>
          <div className={styles.ranges} role="group" aria-label="Chart range">
            {overviewRanges.map(([label]) => <button key={label} aria-pressed={range === label} onClick={() => setRange(label)}>{label}</button>)}
          </div>
        </div>
        <div className={styles.chart}>{chartPoints.length >= 2 ? <IndexChart points={chartPoints} name="Portfolio value" /> : <p className={styles.empty}>At least two stored daily valuations are needed to draw the portfolio value{points.length ? " for this range" : ""}.</p>}</div>
        <dl className={styles.stats}>
          <Stat label="Cash" value={pkr(cash)} note={share(cash)} />
          <Stat label="Invested" value={pkr(invested)} note={share(invested)} />
          <Stat label="Day P&L" value={pkr(dayChange, true)} note={formatPercent(dayPercent)} className={tone(dayChange)} />
          <Stat label="Total return" value={pkr(gain, true)} note={formatPercent(gainPercent)} className={tone(gain)} />
          <Stat label="Annualized return" value={cagr == null ? "Unavailable" : formatPercent(cagr * 100)} note={cagr == null ? (data.quant ? "Insufficient history" : "Analytics not loaded") : "Realized CAGR"} className={tone(cagr)} />
          <Stat label="Volatility" value={vol == null ? "Unavailable" : formatPercent(vol * 100, false)} note={vol == null ? (data.quant ? "Insufficient history" : "Analytics not loaded") : "Annualized"} />
        </dl>
      </section>

      <section className={styles.holdings}>
        <div className={styles.tableHead}>
          <h3>Holdings</h3>
          <label className={styles.search}><Icon name="search" size={15} /><input aria-label="Search holdings" placeholder="Search holdings…" value={query} onChange={event => setQuery(event.target.value)} /></label>
        </div>
        {shown.length ? <div className={styles.tableWrap}><table className={styles.table}>
          <thead><tr><th>Symbol</th><th>Name</th><th className={styles.num}>Value</th><th className={styles.num}>Weight</th><th className={styles.num}>Price</th><th className={styles.num}>Day %</th><th className={styles.num}>1Y %</th><th>Trend</th></tr></thead>
          <tbody>{shown.map(row => <HoldingTr key={row.symbol} row={row} website={extras.websites[row.symbol]} loading={!extras.history[row.symbol]} />)}</tbody>
        </table></div> : <p className={styles.empty}>{rows.length ? "No holdings match your search." : "This portfolio has no holdings."}</p>}
        <p className={styles.source}>Values and prices from stored holdings and database market prices. 1Y % and trend use stored daily closes; 1Y shows — when history is shorter than about 11 months.</p>
      </section>
    </div>

    <aside className={styles.rail} aria-label="Portfolio brief">
      <section>
        <h3>Portfolio brief</h3>
        {brief ? <><p className={styles.lead}>{brief.title}</p><p className={styles.leadText}>{brief.text}</p></> : <p className={styles.empty}>Day change is unavailable, so no brief can be generated.</p>}
        <p className={styles.time}>{benchmark?.percent != null ? `${benchmark.name} as of ${formatDate(benchmark.date)}` : extras.index.failed ? "Benchmark comparison unavailable" : "Generated from stored valuations"}</p>
      </section>
      <section><h3>Top contributors</h3><Movers rows={contributors} websites={extras.websites} empty="No holdings with a positive stored day change." /></section>
      <section><h3>Top detractors</h3><Movers rows={detractors} websites={extras.websites} empty="No holdings with a negative stored day change." /></section>
      <section>
        <h3>Key risks</h3>
        {extras.alerts.failed ? <p className={styles.empty}>Alerts could not be loaded.</p> : extras.alerts.value == null ? <p className={styles.empty}>Loading…</p> : extras.alerts.value.length ? extras.alerts.value.slice(0, 3).map((alert, index) => <article className={styles.item} key={String(alert.id ?? index)}>
          <h4>{humanize(String(alert.alert_type ?? "alert"))} <span className={styles.muted}>· {String(alert.severity ?? "")}</span></h4><p>{String(alert.message ?? "")}</p>{alert.created_at ? <small>{timeAgo(String(alert.created_at))}</small> : null}
        </article>) : <p className={styles.empty}>No active monitoring alerts for this portfolio.</p>}
        {extras.events.value?.events.slice(0, 2).map(({ event, potentially_affected_weight }) => <article className={styles.item} key={event.id}>
          <h4>{event.title}</h4><p>{potentially_affected_weight != null ? `Touches ${formatNumber(potentially_affected_weight, 1)}% of portfolio weight.` : "Affected weight unavailable."}</p><small>{humanize(event.event_type)} · {formatDate(event.occurred_at)}</small>
        </article>)}
      </section>
      <section>
        <h3>Portfolio activity</h3>
        {extras.transactions.failed ? <p className={styles.empty}>Transactions could not be loaded.</p> : extras.transactions.value == null ? <p className={styles.empty}>Loading…</p> : extras.transactions.value.length ? [...extras.transactions.value].sort((a, b) => b.transaction_date.localeCompare(a.transaction_date)).slice(0, 3).map(tx => {
          const line = activityLine(tx);
          return <article className={styles.item} key={tx.id}><h4>{line.title}</h4><p>{line.text}</p><small>{formatDate(tx.transaction_date)}</small></article>;
        }) : <p className={styles.empty}>No transactions recorded.</p>}
      </section>
    </aside>
  </div>;
}

function Stat({ label, value, note, className = "" }: { label: string; value: string; note?: string; className?: string }) {
  return <div><dt>{label}</dt><dd className={className}>{value}</dd>{note ? <small className={className}>{note}</small> : null}</div>;
}

function HoldingTr({ row, website, loading }: { row: HoldingRow; website?: string | null; loading: boolean }) {
  return <tr>
    <td><Link href={`/companies/${row.symbol}` as never} className={styles.symbol}><CompanyLogo symbol={row.symbol} website={website} /><b>{row.symbol}</b></Link></td>
    <td><div className={styles.name} title={row.name}>{row.name}</div></td>
    <td className={styles.num}>{pkr(row.value)}</td>
    <td className={styles.num}>{row.weight == null ? "—" : `${row.weight.toFixed(1)}%`}</td>
    <td className={styles.num}>{formatNumber(row.price)}</td>
    <td className={`${styles.num} ${tone(row.dayPercent)}`}>{formatPercent(row.dayPercent)}</td>
    <td className={`${styles.num} ${tone(row.oneYear)}`}>{loading ? "" : formatPercent(row.oneYear)}</td>
    <td>{loading ? null : <SparkPath values={row.trend} width={80} height={24} />}</td>
  </tr>;
}

function Movers({ rows, websites, empty }: { rows: HoldingRow[]; websites: Record<string, string | null | undefined>; empty: string }) {
  if (!rows.length) return <p className={styles.empty}>{empty}</p>;
  return <>{rows.map(row => <div className={styles.mover} key={row.symbol}>
    <CompanyLogo symbol={row.symbol} website={websites[row.symbol]} size={28} /><b>{row.symbol}</b><span className={`${styles.name} ${styles.muted}`}>{row.name}</span>
    <span className={tone(row.dayChange)}>{pkr(row.dayChange, true)}</span><span className={tone(row.dayPercent)}>{formatPercent(row.dayPercent)}</span>
  </div>)}</>;
}
