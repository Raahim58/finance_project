"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Icon } from "@/components/Icon";
import type { Company, MarketPrice, SectorDailyStats } from "@/lib/api";
import type { ResearchEventView } from "@/lib/api/research";
import { clearApiCache } from "@/lib/api";
import { formatDate, formatNumber, formatPercent, humanize, numeric } from "@/lib/overview";
import { chartRanges, closePoints, sliceRange, timeAgo, yearExtremes, type ChartRange } from "@/lib/markets";
import type { Resource } from "@/components/overview/useOverviewData";
import { CompanyLogo } from "./CompanyLogo";
import { IndexChart } from "./IndexChart";
import { CompanyTrend } from "./Sparkline";
import { useMarketsData } from "./useMarketsData";
import styles from "./markets.module.css";

type Data = ReturnType<typeof useMarketsData>;
type View = "index" | "stocks" | "sectors";
const views: Array<[View, string]> = [["index", "KSE-100"], ["stocks", "All stocks"], ["sectors", "Sectors"]];
const tone = (value: unknown) => { const n = numeric(value); return n == null || n === 0 ? "" : n > 0 ? styles.positive : styles.negative; };
const signed = (value: unknown, digits = 2) => { const n = numeric(value); return n == null ? "—" : `${n > 0 ? "+" : ""}${formatNumber(n, digits)}`; };

function Note({ resource, empty }: { resource: Resource<unknown>; empty: string }) {
  return <p className={styles.empty} role={resource.status === "error" ? "alert" : "status"}>
    {resource.status === "loading" ? "Loading…" : resource.status === "error" ? `${empty} ${resource.error ?? ""}` : empty}
  </p>;
}

export function MarketsPage() {
  const data = useMarketsData();
  const [view, setView] = useState<View>("index");
  const [query, setQuery] = useState("");
  const snapshot = data.market.data?.snapshot;
  const fresh = data.freshness.data;
  const bySymbol = useMemo(() => new Map((data.companies.data ?? []).map(company => [company.symbol, company])), [data.companies.data]);
  const changeBySymbol = useMemo(() => new Map([...(data.market.data?.top_gainers ?? []), ...(data.market.data?.top_losers ?? []), ...(data.market.data?.top_volume ?? [])].map(row => [row.symbol, row.change_percent])), [data.market.data]);
  const failed = [data.market, data.freshness, data.events, data.history, data.companies].some(resource => resource.status === "error");
  return <div className={styles.page}>
    <div className={styles.main}>
      <p className={styles.dateline}>
        <span>{snapshot ? new Date(`${snapshot.snapshot_date}T00:00:00`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" }) : "Date unavailable"}</span>
        <span>{fresh ? `Market ${fresh.exchange_session_status === "unknown" ? "session unknown" : fresh.exchange_session_status}` : "Session unavailable"}</span>
        {snapshot ? <span>{snapshot.index_name} <b className={tone(snapshot.index_change_percent)}>{formatPercent(snapshot.index_change_percent)}</b></span> : null}
      </p>
      <h1 className={styles.title}>Markets</h1>
      {fresh?.market_data_mode === "mock" || fresh?.is_stale || fresh?.provider_mode_warning || fresh?.ingestion_staleness_warning ? <div className={styles.notice} role="status"><Icon name="warning" size={15} />
        <span>{fresh.market_data_mode === "mock" ? "Demo market data" : "Market data needs review"}{[fresh.provider_mode_warning, fresh.ingestion_staleness_warning, fresh.stale_warning].filter(Boolean).slice(0, 1).map(text => ` · ${text}`)}</span></div> : null}
      {failed ? <div className={styles.notice} role="status"><span>Some sections could not be loaded. Available data is shown below.</span><button onClick={() => { clearApiCache(); data.reload(); }}>Retry</button></div> : null}
      <nav className={styles.tabs} aria-label="Market views">{views.map(([key, label]) => <button key={key} aria-current={view === key ? "page" : undefined} onClick={() => setView(key)}>{label}</button>)}</nav>
      {view === "index" ? <IndexPanel data={data} /> : view === "stocks" ? <StocksPanel companies={data.companies} query={query} setQuery={setQuery} changes={changeBySymbol} /> : <SectorsPanel resource={data.market} />}
      {view === "index" ? <>
        <MoversPanels data={data} bySymbol={bySymbol} query={query} setQuery={setQuery} />
        <SectorSummary resource={data.market} onViewAll={() => setView("sectors")} />
      </> : null}
      <p className={styles.source}>{fresh?.latest_used_provider ?? fresh?.latest_source ?? snapshot?.source ?? "Source unavailable"} · trade date {formatDate(snapshot?.snapshot_date ?? fresh?.latest_trade_date)}{fresh?.ingestion_age_seconds != null ? ` · ingested ${Math.round(fresh.ingestion_age_seconds / 60)} min ago` : ""}</p>
    </div>
    <MarketBrief events={data.events} changes={changeBySymbol} />
  </div>;
}

function IndexPanel({ data }: { data: Data }) {
  const [range, setRange] = useState<ChartRange>("1M");
  const snapshot = data.market.data?.snapshot;
  const all = useMemo(() => closePoints(data.history.data ?? []), [data.history.data]);
  const shown = useMemo(() => sliceRange(all, range), [all, range]);
  const extremes = useMemo(() => yearExtremes(all), [all]);
  if (!snapshot) return <section className={styles.hero}><Note resource={data.market} empty="Market snapshot unavailable." /></section>;
  const previous = numeric(snapshot.index_value) != null && numeric(snapshot.index_change) != null ? Number(snapshot.index_value) - Number(snapshot.index_change) : null;
  return <section className={styles.hero} aria-label={`${snapshot.index_name} performance`}>
    <div className={styles.heroTop}>
      <div><h2>{snapshot.index_name}</h2><strong className={styles.level}>{formatNumber(snapshot.index_value)}</strong>
        <p className={`${styles.change} ${tone(snapshot.index_change_percent)}`}>{signed(snapshot.index_change)} &nbsp;{formatPercent(snapshot.index_change_percent)} <span>latest session</span></p></div>
      <div className={styles.ranges} role="group" aria-label="Chart range">{chartRanges.map(([label]) => <button key={label} aria-pressed={range === label} onClick={() => setRange(label)}>{label}</button>)}</div>
    </div>
    {data.history.status === "ready" ? <IndexChart points={shown} name={snapshot.index_name} /> : <Note resource={data.history} empty="Index history unavailable." />}
    <dl className={styles.stats}>
      <Stat label="Previous close" value={formatNumber(previous)} />
      <Stat label="52W high (close)" value={formatNumber(extremes?.high.close)} />
      <Stat label="52W low (close)" value={formatNumber(extremes?.low.close)} />
      <Stat label="Volume" value={formatNumber(snapshot.total_volume, 1, true)} />
      <Stat label="Value traded" value={`PKR ${formatNumber(snapshot.total_value, 1, true)}`} />
    </dl>
    {snapshot.totals_note ? <p className={styles.source}>{snapshot.totals_note}</p> : null}
  </section>;
}

const Stat = ({ label, value }: { label: string; value: string }) => <div><dt>{label}</dt><dd>{value}</dd></div>;

function SearchBox({ companies, query, setQuery }: { companies: Company[]; query: string; setQuery: (value: string) => void }) {
  const needle = query.trim().toLowerCase();
  const matches = needle ? companies.filter(company => company.symbol.toLowerCase().includes(needle) || company.name.toLowerCase().includes(needle)).slice(0, 8) : [];
  return <div className={styles.search}><Icon name="search" size={15} /><input aria-label="Search stocks" placeholder="Search stocks, sectors…" value={query} onChange={event => setQuery(event.target.value)} />
    {needle ? <div className={styles.results}>{matches.length ? matches.map(company => <Link key={company.symbol} href={`/companies/${company.symbol}` as never}><CompanyLogo symbol={company.symbol} website={company.official_website} size={22} /><b>{company.symbol}</b><span>{company.name}</span></Link>) : <p>No active company matches “{query}”.</p>}</div> : null}</div>;
}

function MoversPanels({ data, bySymbol, query, setQuery }: { data: Data; bySymbol: Map<string, Company>; query: string; setQuery: (value: string) => void }) {
  const [side, setSide] = useState<"top_gainers" | "top_losers">("top_gainers");
  const market = data.market.data;
  return <section className={styles.movers} aria-label="Movers">
    <div className={styles.moversBar}><h2>Movers</h2><SearchBox companies={data.companies.data ?? []} query={query} setQuery={setQuery} /></div>
    <div className={styles.moverGrid}>
      <MoverTable title={side === "top_gainers" ? "Top gainers" : "Top losers"} rows={market?.[side] ?? []} bySymbol={bySymbol} resource={data.market}
        toggle={<div className={styles.toggle}>{([["top_gainers", "Gainers"], ["top_losers", "Losers"]] as const).map(([key, label]) => <button key={key} aria-pressed={side === key} onClick={() => setSide(key)}>{label}</button>)}</div>} />
      <MoverTable title="Top by volume" rows={market?.top_volume ?? []} bySymbol={bySymbol} resource={data.market} />
    </div>
  </section>;
}

function MoverTable({ title, rows, bySymbol, resource, toggle }: { title: string; rows: MarketPrice[]; bySymbol: Map<string, Company>; resource: Resource<unknown>; toggle?: React.ReactNode }) {
  return <div className={styles.table}>
    <div className={styles.tableHead}><h3>{title}</h3>{toggle}</div>
    {rows.length ? <table><thead><tr><th>#</th><th>Symbol</th><th>Price</th><th>Day %</th><th>Volume</th><th>30D trend</th></tr></thead>
      <tbody>{rows.map((row, index) => <tr key={row.symbol}>
        <td>{index + 1}</td>
        <td><Link href={`/companies/${row.symbol}` as never} className={styles.symbol}><CompanyLogo symbol={row.symbol} website={bySymbol.get(row.symbol)?.official_website} /><b>{row.symbol}</b></Link></td>
        <td>{formatNumber(row.close)}</td><td className={tone(row.change_percent)}>{formatPercent(row.change_percent)}</td><td>{formatNumber(row.volume, 1, true)}</td>
        <td><CompanyTrend symbol={row.symbol} /></td></tr>)}</tbody></table> : <Note resource={resource} empty={`${title} unavailable.`} />}
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

function SectorsPanel({ resource }: { resource: Resource<{ sectors: SectorDailyStats[] }> }) {
  const sectors = rankedSectors(resource.data?.sectors ?? []);
  return <section className={styles.sectors}>
    {sectors.length ? <table><thead><tr><th>#</th><th>Sector</th><th>Day %</th><th>Advancers</th><th>Decliners</th><th>Unchanged</th><th>Volume</th><th>Value traded</th></tr></thead>
      <tbody>{sectors.map((sector, index) => <tr key={sector.sector}><td>{index + 1}</td><td>{sector.sector}</td><td className={tone(sector.average_change_percent)}>{formatPercent(sector.average_change_percent)}</td><td>{sector.advancers}</td><td>{sector.decliners}</td><td>{sector.unchanged}</td><td>{formatNumber(sector.total_volume, 1, true)}</td><td>{formatNumber(sector.total_value, 1, true)}</td></tr>)}</tbody></table>
      : <Note resource={resource} empty="Sector statistics unavailable." />}
  </section>;
}

function StocksPanel({ companies, query, setQuery, changes }: { companies: Resource<Company[]>; query: string; setQuery: (value: string) => void; changes: Map<string, string> }) {
  const needle = query.trim().toLowerCase();
  const rows = (companies.data ?? []).filter(company => !needle || company.symbol.toLowerCase().includes(needle) || company.name.toLowerCase().includes(needle) || company.sector.toLowerCase().includes(needle));
  return <section className={styles.sectors}>
    <div className={styles.moversBar}><h2>{rows.length} companies</h2>
      <div className={styles.search}><Icon name="search" size={15} /><input aria-label="Filter stocks" placeholder="Filter by symbol, name or sector…" value={query} onChange={event => setQuery(event.target.value)} /></div></div>
    {rows.length ? <div className={styles.directory}><table><thead><tr><th>Symbol</th><th>Company</th><th>Sector</th><th>Day %</th></tr></thead>
      <tbody>{rows.slice(0, 200).map(company => <tr key={company.symbol}>
        <td><Link href={`/companies/${company.symbol}` as never} className={styles.symbol}><CompanyLogo symbol={company.symbol} website={company.official_website} /><b>{company.symbol}</b></Link></td>
        <td>{company.name}</td><td>{company.sector}</td><td className={tone(changes.get(company.symbol))}>{changes.has(company.symbol) ? formatPercent(changes.get(company.symbol)) : "—"}</td></tr>)}</tbody></table>
      {rows.length > 200 ? <p className={styles.source}>Showing 200 of {rows.length}; refine the filter to narrow.</p> : null}</div> : <Note resource={companies} empty={needle ? `No active company matches “${query}”.` : "No active companies are available."} />}
  </section>;
}

function MarketBrief({ events, changes }: { events: Resource<ResearchEventView[]>; changes: Map<string, string> }) {
  const rows = events.data ?? [];
  const [lead, ...rest] = rows;
  const snippet = (event: ResearchEventView) => { const text = event.evidence[0]?.text?.replace(/\s+/g, " ").trim(); return text ? (text.length > 190 ? `${text.slice(0, 187)}…` : text) : null; };
  return <aside className={styles.rail} aria-label="Market brief">
    <div className={styles.railHead}><h2>Market brief</h2><Link href={"/research" as never}>View all <span aria-hidden="true">→</span></Link></div>
    {lead ? <>
      <h3 className={styles.lead}>{lead.title}</h3>
      {snippet(lead) ? <p className={styles.leadText}>{snippet(lead)}</p> : null}
      <p className={styles.time}>{timeAgo(lead.occurred_at)} · {humanize(lead.event_type)}{lead.evidence[0]?.source_name ? ` · ${lead.evidence[0].source_name}` : ""}</p>
      <div className={styles.items}>{rest.slice(0, 6).map(event => <article key={event.event_key}>
        <div><h4>{event.title}</h4><span className={`${styles.badge} ${event.materiality === "high" ? styles.badgeHigh : ""}`}>{humanize(event.materiality)}</span></div>
        {snippet(event) ? <p>{snippet(event)}</p> : null}
        <p className={styles.meta}><span>{timeAgo(event.occurred_at)}</span><span>{humanize(event.source_document_type)}</span>
          {event.subjects.slice(0, 3).map(subject => <Link key={subject.subject_key} href={`/companies/${subject.subject_key}` as never}>{subject.subject_key}{changes.has(subject.subject_key) ? <b className={tone(changes.get(subject.subject_key))}> {formatPercent(changes.get(subject.subject_key))}</b> : null}</Link>)}</p>
      </article>)}</div></> : <Note resource={events} empty="No dated market events are stored yet." />}
  </aside>;
}
