"use client";

import Link from "next/link";
import { useState } from "react";
import { Icon } from "@/components/Icon";
import { EvidenceDrawer } from "@/components/ResearchEventCard";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
import { clearApiCache } from "@/lib/api";
import { formatDate, formatNumber, formatPercent, humanize, investigationSignals, marketBreadth, numeric, performanceSeries, signalFilters, visibleSignals, type SignalFilter } from "@/lib/overview";
import { OverviewPerformanceChart } from "./OverviewPerformanceChart";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { useOverviewData, type Resource } from "./useOverviewData";
import styles from "./overview.module.css";

type OverviewData = ReturnType<typeof useOverviewData>;
const tone = (value: unknown) => { const number = numeric(value); return number == null || number === 0 ? "" : number > 0 ? styles.positive : styles.negative; };

function State({ resource, empty }: { resource: Resource<unknown>; empty: string }) {
  return <p className={styles.empty} role={resource.status === "error" ? "alert" : "status"}>
    {resource.status === "loading" ? "Loading…" : resource.status === "error" ? `${empty} ${resource.error ?? "Try refreshing."}` : empty}
  </p>;
}

export function OverviewPage() {
  const data = useOverviewData();
  const assistant = useAssistantWorkspace();
  const fresh = data.freshness.data;
  const hasError = [data.market, data.freshness, data.events, data.regime, data.portfolios, data.summary, data.performance, data.alerts, data.compliance, data.exposure].some(resource => resource.status === "error");
  return <div className={styles.page}>
    <WorkspaceHeader title="Today"/>
    <div className={styles.sessionLine}><span>The market today</span><span>PSX · {fresh?humanize(fresh.exchange_session_status):"Session unavailable"} · Data as of {formatDate(data.market.data?.snapshot?.snapshot_date??fresh?.latest_trade_date)}</span></div>
    {fresh?.is_stale || fresh?.market_data_mode === "mock" ? <div className={styles.dataNotice} role="status"><Icon name="warning" size={16} /><span>{fresh.market_data_mode === "mock" ? "Demo market data" : "Market data needs review"}{fresh.stale_warning ? ` · ${fresh.stale_warning}` : ""}</span><Link href="/market">View market context <Arrow /></Link></div> : null}
    {hasError ? <div className={styles.dataNotice} role="status"><span>Some sections could not be loaded. Available data is shown below.</span><button onClick={() => { clearApiCache(); data.reload(); }}>Retry unavailable data <Arrow /></button></div> : null}
    <MarketSnapshot data={data} />
    <div className={styles.middleGrid}><Investigations data={data} /><PortfolioPulse data={data} /></div>
    <div className={styles.bottomGrid}><MaterialEvents data={data} /><MacroContext data={data} /></div>
    <footer className={styles.footer}><button onClick={() => { clearApiCache(); data.reload(); }}><Icon name="clock" size={14} />Refresh overview</button>{assistant ? <button onClick={() => assistant.open()}><Icon name="assistant" size={16} />Ask this workspace</button> : null}</footer>
  </div>;
}

function Arrow() { return <span className={styles.arrow} aria-hidden="true">→</span>; }

function MarketSnapshot({ data }: { data: OverviewData }) {
  const snapshot = data.market.data?.snapshot;
  const breadth = marketBreadth(data.market.data);
  const total = breadth ? breadth.advancers + breadth.decliners + breadth.unchanged : 0;
  return <section className={`${styles.surface} ${styles.snapshot}`} aria-labelledby="market-snapshot-heading">
    <div className={styles.index}><h2 id="market-snapshot-heading">Market snapshot</h2>
      {snapshot ? <><div className={styles.indexHeadline}><h3>{snapshot.index_name}</h3><strong>{formatNumber(snapshot.index_value)}</strong><span className={tone(snapshot.index_change_percent)}>{numeric(snapshot.index_change) != null && Number(snapshot.index_change) > 0 ? "+" : ""}{formatNumber(snapshot.index_change)} ({formatPercent(snapshot.index_change_percent)})</span></div>
        <dl className={styles.tradingStats}><div><dt>Volume</dt><dd>{formatNumber(snapshot.total_volume, 1, true)}</dd></div><div><dt>Value traded</dt><dd>PKR {formatNumber(snapshot.total_value, 1, true)}</dd></div></dl>
        <p className={styles.source}>Daily snapshot · {formatDate(snapshot.snapshot_date)} · {snapshot.source || "Source unavailable"}</p></> : <State resource={data.market} empty="Market snapshot unavailable." />}
    </div>
    <div className={styles.breadth}><h2>Market breadth</h2>{breadth ? <>
      <dl className={styles.breadthCounts}><div><dd className={styles.positive}>{formatNumber(breadth.advancers, 0)}</dd><dt>Advancers</dt></div><div><dd className={styles.negative}>{formatNumber(breadth.decliners, 0)}</dd><dt>Decliners</dt></div><div><dd>{formatNumber(breadth.unchanged, 0)}</dd><dt>Unchanged</dt></div></dl>
      <div className={styles.breadthBar} aria-label={`${breadth.advancers} advancers, ${breadth.decliners} decliners, ${breadth.unchanged} unchanged`}>
        {total > 0 ? <><span style={{ width: `${breadth.advancers / total * 100}%` }} /><span style={{ width: `${breadth.decliners / total * 100}%` }} /><span style={{ width: `${breadth.unchanged / total * 100}%` }} /></> : null}
      </div><p className={styles.source}>{formatDate(breadth.date)} · {breadth.sources || "Source unavailable"}</p>
    </> : <State resource={data.market} empty="Breadth unavailable for this market session." />}</div>
  </section>;
}

function Investigations({ data }: { data: OverviewData }) {
  const [filter, setFilter] = useState<SignalFilter>("All");
  const signals = visibleSignals(investigationSignals({ market: data.market.data, events: data.events.data ?? [], exposure: data.exposure.data, regime: data.regime.data }), filter);
  const resources = [data.market, data.events, data.exposure, data.regime];
  return <section className={`${styles.surface} ${styles.investigations}`} aria-labelledby="investigate-heading">
    <div className={styles.sectionHead}><h2 id="investigate-heading">Worth investigating</h2></div>
    <div className={styles.filters} role="group" aria-label="Investigation category">{signalFilters.map(category => <button key={category} aria-pressed={category === filter} onClick={() => setFilter(category)}>{category}</button>)}</div>
    <div className={styles.signals}>{signals.length ? signals.map(signal => <Link key={signal.id} href={signal.href as never} className={styles.signal}>
      <div><strong>{signal.title}</strong><small>{signal.category}</small></div>
      <span className={`${styles.signalValue} ${signal.tone === "positive" ? styles.positive : signal.tone === "negative" ? styles.negative : ""}`}>{signal.value}</span>
      <div className={styles.signalReason}><span>{signal.reason}</span><small>{signal.source}{signal.date ? ` · ${formatDate(signal.date)}` : ""}</small></div><Arrow />
    </Link>) : <p className={styles.empty} role="status">{resources.some(resource => resource.status === "loading") ? "Loading investigation signals…" : resources.some(resource => resource.status === "error") ? "Signals could not be fully loaded. Try refreshing." : "No available signals in this category."}</p>}</div>
  </section>;
}

function PortfolioPulse({ data }: { data: OverviewData }) {
  const summary = data.summary.data;
  const selected = data.portfolios.data?.find(portfolio => portfolio.id === data.portfolioId);
  const series = performanceSeries(data.performance.data ?? []);
  const cashWeight = summary?.valuation_complete && numeric(summary.total_value) != null && Number(summary.total_value) > 0 && numeric(summary.cash_balance) != null ? Number(summary.cash_balance) / Number(summary.total_value) * 100 : null;
  const compliance = data.compliance.data;
  const alerts = data.alerts.data;
  const breachCount = alerts?.filter(alert => alert.classification === "mandate_breach").length ?? 0;
  const warningCount = alerts == null ? null : alerts.length - breachCount;
  const currency = summary?.portfolio.base_currency ?? selected?.base_currency;
  return <section className={`${styles.surface} ${styles.portfolio}`} aria-labelledby="portfolio-pulse-heading">
    <div className={styles.sectionHead}><h2 id="portfolio-pulse-heading">Your portfolio</h2><span className={styles.scopeLabel}>{selected?.name ?? "No portfolio selected"}</span></div>
    {!data.portfolioId ? <div className={styles.empty}><p>{data.portfolios.status === "loading" ? "Loading portfolios…" : data.portfolios.status === "error" ? "Portfolios could not be loaded." : "Select a portfolio to see value and performance."}</p><Link href="/portfolios/manage">Manage portfolios <Arrow /></Link></div> : !summary ? <State resource={data.summary} empty="Portfolio valuation unavailable." /> : <>
      <div className={styles.portfolioHeadline}><strong>{currency} {formatNumber(summary.total_value, 0)}</strong><div className={tone(summary.day_change_percent)}><span>{formatPercent(summary.day_change_percent)} today</span><small>{numeric(summary.day_change) != null && Number(summary.day_change) > 0 ? "+" : ""}{currency} {formatNumber(summary.day_change, 0)}</small></div></div>
      {!summary.valuation_complete ? <p className={styles.inlineWarning}>Partial valuation · {summary.valuation_note || `Unpriced holdings: ${summary.unpriced_symbols.join(", ")}`}</p> : null}
      <dl className={styles.portfolioMetrics}><div><dt>Cumulative TWR</dt><dd className={tone(series.at(-1)?.value)}>{formatPercent(series.at(-1)?.value)}</dd></div><div><dt>Holdings</dt><dd>{summary.holdings.length}</dd></div><div><dt>Cash</dt><dd>{formatPercent(cashWeight, false)}</dd></div></dl>
      {data.performance.status !== "ready" ? <State resource={data.performance} empty="Portfolio performance unavailable." /> : <OverviewPerformanceChart points={data.performance.data ?? []} />}
      <div className={styles.chartCaption}><span><i />Time-weighted return</span><span>{formatDate(series.at(-1)?.date)}</span></div>
      <p className={styles.source}>{humanize(summary.portfolio.source_mode)} portfolio · {summary.data_source || "Source unavailable"} · Prices as of {formatDate(summary.data_freshness_date)}</p>
      {!summary.portfolio.history_complete ? <p className={styles.source}>History begins at the recorded opening balance.</p> : null}
    </>}
    {data.portfolioId ? <div className={styles.portfolioStatus}>
      <div>{alerts == null ? <span>{data.alerts.status === "loading" ? "Loading monitoring…" : "Monitoring unavailable"}</span> : <><span>{warningCount} active monitoring warning{warningCount === 1 ? "" : "s"}{breachCount ? ` · ${breachCount} mandate breach${breachCount === 1 ? "" : "es"}` : ""}</span><Link href="/monitoring">Review alerts <Arrow /></Link></>}</div>
      <div><span className={compliance?.status === "BREACH" ? styles.negative : ""}>Mandate: {compliance?.status === "PASS" ? "within evaluated limits" : compliance?.status === "BREACH" ? "breach" : data.compliance.status === "loading" ? "loading…" : "not fully evaluated"}</span><Link href={`/portfolios/${encodeURIComponent(data.portfolioId)}/overview` as never}>Open portfolio <Arrow /></Link></div>
    </div> : null}
  </section>;
}

function MaterialEvents({ data }: { data: OverviewData }) {
  return <section className={`${styles.surface} ${styles.events}`} aria-labelledby="material-events-heading">
    <div className={styles.sectionHead}><h2 id="material-events-heading">Material events</h2><Link href="/research">View all research <Arrow /></Link></div>
    {data.events.data?.length ? data.events.data.slice(0, 3).map(event => <article className={styles.event} key={event.event_key}>
      <time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time><div><strong>{event.subjects.map(subject => subject.subject_key).join(", ") || humanize(event.event_type)}</strong><p>{event.title}</p><small>{humanize(event.event_type)} · {humanize(event.freshness_status)}</small></div>
      <span className={`${styles.materiality} ${event.materiality === "high" ? styles.high : event.materiality === "medium" ? styles.medium : ""}`}>{humanize(event.materiality || "Not rated")}</span>
      <details className={styles.eventEvidence}><summary>View evidence <Arrow /></summary><EvidenceDrawer evidence={event.evidence} /></details>
    </article>) : <State resource={data.events} empty="No material events returned from stored evidence." />}
  </section>;
}

const dimensionLabels: Record<string, string> = { rates: "Rates", currency: "USD/PKR", inflation: "Inflation", oil: "Oil", market_breadth: "Market breadth" };
function MacroContext({ data }: { data: OverviewData }) {
  const regime = data.regime.data;
  const rows = Object.entries(regime?.dimensions ?? {});
  return <section className={`${styles.surface} ${styles.macro}`} aria-labelledby="macro-heading">
    <div className={styles.sectionHead}><h2 id="macro-heading">Macro & market context</h2></div>
    {regime ? <><div className={styles.macroBody}><div><strong className={styles.regime}>{humanize(regime.regime)}</strong><p className={styles.source}>Rules-based assessment</p></div><dl className={styles.dimensions}>{rows.map(([key, row]) => {
      const status = String(row.status ?? "not_evaluated");
      const arrow = status === "rising" || status === "positive" ? "↑" : status === "falling" || status === "negative" ? "↓" : status === "flat" ? "→" : "—";
      return <div key={key}><dt><span aria-hidden="true">{arrow}</span>{dimensionLabels[key] ?? humanize(key)}</dt><dd>{humanize(status)}{numeric(row.value) != null ? ` · ${formatNumber(row.value)} ${String(row.unit ?? "")}` : ""}<small>{String(row.series_name ?? (Array.isArray(row.source) ? row.source.join(" · ") : row.source ?? "Source unavailable"))} · {formatDate(String(row.effective_date ?? row.trade_date ?? ""))}</small></dd></div>;
    })}</dl></div><p className={styles.method}>{regime.method_note}</p><Link className={styles.macroLink} href="/market">View observations & method <Arrow /></Link></> : <State resource={data.regime} empty="Macro assessment unavailable." />}
  </section>;
}
