"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Icon } from "@/components/Icon";
import type { Company, MarketPrice, SectorDailyStats } from "@/lib/api";
import { clearApiCache } from "@/lib/api";
import { formatDate, formatNumber, formatPercent, numeric } from "@/lib/overview";
import { chartRanges, closePoints, indexLatest, sliceRange, timeAgo, yearExtremes, type ChartRange } from "@/lib/markets";
import type { Resource } from "@/components/overview/useOverviewData";
import { CompanyLogo } from "./CompanyLogo";
import { IndexChart } from "./IndexChart";
import { SparkPath } from "./Sparkline";
import { useMarketsData } from "./useMarketsData";
import { MarketCatalog, type MarketView } from "./MarketCatalog";
import { MarketDigest } from "./MarketDigest";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { MarketDetailRail,type MarketSelection } from "./MarketDetailRail";
import { MarketRail } from "./MarketRail";
import { useBrief } from "@/components/AIBriefCard";
import { getMarketBrief } from "@/lib/api/research";
import styles from "./markets.module.css";

type Data = ReturnType<typeof useMarketsData>;
const tone = (value: unknown) => { const n = numeric(value); return n == null || n === 0 ? "" : n > 0 ? styles.positive : styles.negative; };
const signed = (value: unknown, digits = 2) => { const n = numeric(value); return n == null ? "—" : `${n > 0 ? "+" : ""}${formatNumber(n, digits)}`; };

function Note({ resource, empty }: { resource: Resource<unknown>; empty: string }) {
  return <p className={styles.empty} role={resource.status === "error" ? "alert" : "status"}>
    {resource.status === "loading" ? "Loading…" : resource.status === "error" ? `${empty} ${resource.error ?? ""}` : empty}
  </p>;
}

export function MarketsPage() {
  const data = useMarketsData();
  const brief = useBrief(getMarketBrief);
  const [view, setView] = useState<MarketView>("index");
  const [query, setQuery] = useState("");
  const [selection,setSelection]=useState<MarketSelection|null>(null);
  const openCompany=(symbol:string)=>setSelection({kind:"company",symbol});
  const openSector=(sector:string)=>setSelection({kind:"sector",sector});
  const snapshot = data.market.data?.snapshot;
  const fresh = data.freshness.data;
  const session = data.market.data;
  const latest = useMemo(() => indexLatest(data.history.data ?? [], snapshot), [data.history.data, snapshot]);
  const bySymbol = useMemo(() => new Map((data.companies.data ?? []).map(company => [company.symbol, company])), [data.companies.data]);
  const prices = useMemo(() => new Map((session?.prices ?? []).map(row => [row.symbol, row])), [session]);
  const changeBySymbol = useMemo(() => new Map((session?.prices ?? [...(session?.top_gainers ?? []), ...(session?.top_losers ?? []), ...(session?.top_volume ?? [])]).map(row => [row.symbol, row.change_percent])), [session]);
  const failed = [data.market, data.freshness, data.events, data.history, data.companies].some(resource => resource.status === "error");
  return <div className={styles.page}>
    <WorkspaceHeader title=""><nav className="workspace-header-tabs" aria-label="Market views">{([["index","Market digest"],["stocks","All stocks"],["sectors","Sectors"],["events","Events"]] as const).map(([key,label])=><button key={key} aria-current={view===key?"page":undefined} onClick={()=>setView(key)}>{label}</button>)}</nav><button className="workspace-header-action" aria-label="Refresh market view" onClick={()=>{clearApiCache();data.reload()}}><Icon name="clock" size={15}/></button></WorkspaceHeader>
    <MarketCatalog view={view} select={setView} market={session ?? null} freshness={fresh} companies={data.companies.data ?? []} onCompany={openCompany} chart={<IndexPanel data={data} />} />
    <div className={styles.main}>
      <p className={styles.dateline}>
        <span>{(session?.trade_date ?? fresh?.latest_trade_date ?? latest?.date) ? new Date(`${session?.trade_date ?? fresh?.latest_trade_date ?? latest?.date}T00:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" }) : "Date unavailable"}</span>
        <span>{fresh ? `Market ${fresh.exchange_session_status === "unknown" ? "session unknown" : fresh.exchange_session_status}` : "Session unavailable"}</span>
        {latest?.percent != null ? <span>{latest.name} <b className={tone(latest.percent)}>{formatPercent(latest.percent)}</b></span> : null}
      </p>
      {session?.trade_date ? <p className={styles.source} role="status">
        {session.price_basis === "intraday" ? "Observed intraday quotes" : "Latest daily session"} · {formatDate(session.trade_date)} · {session.priced_securities} securities
        {session.observed_at ? ` · Retrieved ${timeAgo(session.observed_at)}` : ""}
        {session.latest_quote_date && session.latest_quote_date > session.trade_date ? ` · ${session.latest_quote_count} newer quotes (${formatDate(session.latest_quote_date)}); insufficient coverage for market rankings` : ""}
      </p> : null}
      {data.freshness.error ? <p className={styles.notice} role="status">{data.freshness.error}</p> : null}
      {fresh?.market_data_mode === "mock" || fresh?.is_stale || fresh?.provider_mode_warning || fresh?.ingestion_staleness_warning ? <div className={styles.notice} role="status"><Icon name="warning" size={15} />
        <span>{fresh.market_data_mode === "mock" ? "Demo market data" : "Market data needs review"}{[fresh.provider_mode_warning, fresh.ingestion_staleness_warning, fresh.stale_warning].filter(Boolean).slice(0, 1).map(text => ` · ${text}`)}</span></div> : null}
      {failed ? <div className={styles.notice} role="status"><span>Some sections could not be loaded. Available data is shown below.</span><button onClick={() => { clearApiCache(); data.reload(); }}>Retry</button></div> : null}
      {view === "stocks" ? <MoversPanels data={data} bySymbol={bySymbol} query={query} setQuery={setQuery} onCompany={openCompany}/> : null}
      {view === "index" ? <MarketDigest brief={brief} market={session ?? null} events={data.events.data ?? []} companies={bySymbol} onStocks={() => setView("stocks")} /> : view === "stocks" ? <StocksPanel companies={data.companies} query={query} setQuery={setQuery} changes={changeBySymbol} prices={prices} onCompany={openCompany} onSector={openSector} selected={selection?.kind==="company"?selection.symbol:undefined}/> : view === "sectors" ? <SectorsPanel resource={data.market} onSector={openSector}/> : <section className={styles.eventList}><h2>Recent market events</h2>{(data.events.data ?? []).map(event => <article key={event.event_key}><small>{formatDate(event.occurred_at)}</small><h3>{event.title}</h3><a href={event.evidence[0]?.source_url ?? "/research"}>{event.evidence[0]?.source_name ?? "View evidence"} ↗</a></article>)}{!data.events.data?.length ? <Note resource={data.events} empty="No selected market event evidence is available." /> : null}</section>}
      <p className={styles.source}>{fresh?.latest_used_provider ?? fresh?.latest_source ?? snapshot?.source ?? "Source unavailable"} · prices as of {formatDate(session?.trade_date ?? fresh?.latest_trade_date ?? snapshot?.snapshot_date)} · refreshes hourly</p>
    </div>
    {selection?<MarketDetailRail key={selection.kind=== "company"?`company:${selection.symbol}`:`sector:${selection.sector}`} selection={selection} companies={data.companies.data??[]} market={session??null} onClose={()=>setSelection(null)} onCompany={openCompany} onSector={openSector}/>:<MarketRail brief={brief} market={session ?? null} events={data.events.data ?? []} loading={data.events.status === "loading"} onSector={openSector}/> }
  </div>;
}

function IndexPanel({ data }: { data: Data }) {
  const [range, setRange] = useState<ChartRange>("1M");
  const snapshot = data.market.data?.snapshot;
  const all = useMemo(() => closePoints(data.history.data ?? []), [data.history.data]);
  const livePoint = snapshot && data.market.data?.price_basis === "intraday" && numeric(snapshot.index_value) != null
    ? { date: snapshot.snapshot_date, close: Number(snapshot.index_value) } : null;
  const shown = useMemo(() => sliceRange(livePoint ? [...all.filter(point => point.date < livePoint.date), livePoint] : all, range), [all, range, livePoint?.date, livePoint?.close]);
  const extremes = useMemo(() => yearExtremes(all), [all]);
  const latest = useMemo(() => indexLatest(data.history.data ?? [], snapshot), [data.history.data, snapshot]);
  if (!latest) return <section className={styles.hero}><Note resource={data.history.status === "ready" ? data.market : data.history} empty="KSE-100 data unavailable." /></section>;
  const previous = latest.level != null && latest.change != null ? latest.level - latest.change : null;
  return <section className={styles.hero} aria-label={`${latest.name} performance`}>
    <div className={styles.heroTop}>
      <div><span className={styles.muted}>{latest.name}</span><strong className={styles.level}>{formatNumber(latest.level)}</strong>
        <p className={`${styles.change} ${tone(latest.percent)}`}>{signed(latest.change)} &nbsp;{formatPercent(latest.percent)} <span>{livePoint ? "observed session" : `stored close · ${formatDate(latest.date)}`}</span></p></div>

    </div>
    {data.history.status === "ready" ? <IndexChart points={shown} name={latest.name} liveDate={livePoint?.date} height={175} /> : <Note resource={data.history} empty="Index history unavailable." />}
    {livePoint ? <p className={styles.chartCaption}>Daily closes with the latest observed index level at the final point.</p> : null}
      <div className={styles.ranges} role="group" aria-label="Chart range">{chartRanges.map(([label]) => <button key={label} aria-pressed={range === label} onClick={() => setRange(label)}>{label}</button>)}</div>
    <details className={styles.indexDetails}><summary>Session statistics</summary><dl className={styles.stats}>
      <Stat label="Previous close" value={formatNumber(previous)} />
      <Stat label="52W high (close)" value={formatNumber(extremes?.high.close)} />
      <Stat label="52W low (close)" value={formatNumber(extremes?.low.close)} />
      <Stat label="Volume" value={snapshot ? formatNumber(snapshot.total_volume, 1, true) : "—"} />
      <Stat label="Value traded" value={snapshot ? `PKR ${formatNumber(snapshot.total_value, 1, true)}` : "—"} />
    </dl></details>
    {snapshot?.totals_note ? <p className={styles.source}>{snapshot.totals_note}</p> : null}
  </section>;
}

const Stat = ({ label, value }: { label: string; value: string }) => <div><dt>{label}</dt><dd>{value}</dd></div>;

function MoversPanels({ data, bySymbol, query, setQuery,onCompany }: { onCompany:(symbol:string)=>void;data: Data; bySymbol: Map<string, Company>; query: string; setQuery: (value: string) => void }) {
  const market = data.market.data;
  return <section className={styles.movers} aria-label="Market movers">
    <div className={styles.moversBar}><h2>Market movers</h2></div>
    <div className={styles.moverGrid}>
      <MoverTable title="Top gainers" rows={market?.top_gainers ?? []} bySymbol={bySymbol} resource={data.market} trends={data.trends} onCompany={onCompany}/>
      <MoverTable title="Top losers" rows={market?.top_losers ?? []} bySymbol={bySymbol} resource={data.market} trends={data.trends} onCompany={onCompany}/>
    </div>
  </section>;
}

function MoverTable({ title, rows, bySymbol, resource, toggle, trends,onCompany }: {onCompany:(symbol:string)=>void; trends: Record<string, number[]>; title: string; rows: MarketPrice[]; bySymbol: Map<string, Company>; resource: Resource<unknown>; toggle?: React.ReactNode }) {
  return <div className={styles.table}>
    <div className={styles.tableHead}><h3>{title}</h3>{toggle}</div>
    {rows.length ? <table><thead><tr><th>#</th><th>Symbol</th><th>Price</th><th>Day %</th><th>Volume</th><th>30D trend</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.symbol}>
        <td>{index + 1}</td>
        <td><button onClick={()=>onCompany(row.symbol)} className={styles.symbol}><CompanyLogo symbol={row.symbol} website={bySymbol.get(row.symbol)?.official_website}/><b>{row.symbol}</b></button></td>
        <td>{formatNumber(row.close)}</td><td className={tone(row.change_percent)}>{formatPercent(row.change_percent)}</td><td>{formatNumber(row.volume, 1, true)}</td>
        <td><SparkPath values={trends[row.symbol] ?? []} /></td></tr>)}</tbody></table> : <Note resource={resource} empty={`${title} unavailable.`} />}
  </div>;
}

function rankedSectors(sectors: SectorDailyStats[]) {
  return sectors.slice().sort((a, b) => Number(b.average_change_percent) - Number(a.average_change_percent));
}

function SectorSummary({ resource, onViewAll }: { resource: Resource<{ sectors: SectorDailyStats[] }>; onViewAll: () => void }) {
  const sectors = rankedSectors(resource.data?.sectors ?? []);
  const top = sectors.length > 10 ? [...sectors.slice(0, 5), ...sectors.slice(-5)] : sectors;
  const ranked = top.map(sector => ({ sector, rank: sectors.indexOf(sector) + 1 }));
  return <section className={styles.sectors} aria-label="Sector performance">
    <div className={styles.tableHead}><h2>Sector performance</h2><button className={styles.link} onClick={onViewAll}>View all <span aria-hidden="true">→</span></button></div>
    {ranked.length ? <div className={styles.sectorCols}>{[ranked.slice(0, Math.ceil(ranked.length / 2)), ranked.slice(Math.ceil(ranked.length / 2))].map((group, i) => <table key={i}>
      <thead><tr><th>#</th><th>Sector</th><th>Day %</th><th>Adv / Dec</th><th>Value traded</th></tr></thead>
      <tbody>{group.map(({ sector, rank }) => <tr key={sector.sector}><td>{rank}</td><td>{sector.sector}</td><td className={tone(sector.average_change_percent)}>{formatPercent(sector.average_change_percent)}</td><td>{sector.advancers} / {sector.decliners}</td><td>{formatNumber(sector.total_value, 1, true)}</td></tr>)}</tbody></table>)}</div> : <Note resource={resource} empty="Sector statistics unavailable." />}
  </section>;
}

function SectorsPanel({ resource,onSector }: {onSector:(sector:string)=>void; resource: Resource<{ sectors: SectorDailyStats[] }> }) {
  const sectors = rankedSectors(resource.data?.sectors ?? []);
  return <section className={styles.sectors}>
    {sectors.length ? <table><thead><tr><th>#</th><th>Sector</th><th>Day %</th><th>Advancers</th><th>Decliners</th><th>Unchanged</th><th>Volume</th><th>Value traded</th></tr></thead>
      <tbody>{sectors.map((sector, index) => <tr key={sector.sector}><td>{index + 1}</td><td><button onClick={()=>onSector(sector.sector)}>{sector.sector}</button></td><td className={tone(sector.average_change_percent)}>{formatPercent(sector.average_change_percent)}</td><td>{sector.advancers}</td><td>{sector.decliners}</td><td>{sector.unchanged}</td><td>{formatNumber(sector.total_volume, 1, true)}</td><td>{formatNumber(sector.total_value, 1, true)}</td></tr>)}</tbody></table>
      : <Note resource={resource} empty="Sector statistics unavailable." />}
  </section>;
}

function StocksPanel({ companies, query, setQuery, changes, prices,onCompany,onSector,selected }: {onSector:(sector:string)=>void;onCompany:(symbol:string)=>void;selected?:string; companies: Resource<Company[]>; query: string; setQuery: (value: string) => void; changes: Map<string, string>; prices: Map<string, MarketPrice> }) {
  const [visible, setVisible] = useState(100);
  const needle = query.trim().toLowerCase();
  const rows = (companies.data ?? []).filter(company => !needle || company.symbol.toLowerCase().includes(needle) || company.name.toLowerCase().includes(needle) || company.sector.toLowerCase().includes(needle));
  return <section className={styles.sectors}>
    <div className={styles.moversBar}><h2>{rows.length} companies</h2>
      <div className={styles.search}><Icon name="search" size={15} /><input aria-label="Filter stocks" placeholder="Filter stocks" value={query} onChange={event => setQuery(event.target.value)} /></div></div>
    {rows.length ? <div className={styles.directory}><table><thead><tr><th>Symbol</th><th>Company</th><th>Sector</th><th>Price (PKR)</th><th>Day %</th><th>Volume</th><th>Quote date</th></tr></thead>
      <tbody>{rows.slice(0, visible).map(company => <tr key={company.symbol} aria-selected={selected===company.symbol}>
        <td><button onClick={()=>onCompany(company.symbol)} className={styles.symbol}><CompanyLogo symbol={company.symbol} website={company.official_website}/><b>{company.symbol}</b></button></td>
        <td>{company.name}</td><td><button onClick={()=>onSector(company.sector)}>{company.sector}</button></td><td>{formatNumber(prices.get(company.symbol)?.close)}</td><td className={tone(changes.get(company.symbol))}>{changes.has(company.symbol) ? formatPercent(changes.get(company.symbol)) : "—"}</td><td>{formatNumber(prices.get(company.symbol)?.volume, 1, true)}</td><td>{prices.has(company.symbol) ? formatDate(prices.get(company.symbol)?.trade_date) : "—"}</td></tr>)}</tbody></table>
      {rows.length > visible ? <button className={styles.loadMore} onClick={() => setVisible(value => value + 100)}>Show more companies · {Math.min(visible, rows.length)} of {rows.length}</button> : null}</div> : <Note resource={companies} empty={needle ? `No active company matches “${query}”.` : "No active companies are available."} />}
  </section>;
}
