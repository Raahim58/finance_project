"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/Icon";
import { LineChart } from "@/components/WorkstationChart";
import { TermHelp, TermLabel } from "@/components/TermHelp";
import {
  CandidateEvaluation,
  CompanyCompleteness,
  CompanyDetail,
  CompanyResearch,
  MarketPrice,
  Portfolio,
  evaluateSecurity,
  getCompanyCompleteness,
  getCompanyDetail,
  getCompanyHistory,
  getCompanyResearch,
  getContextRefresh,
  deactivateContextRefresh,
  getPortfolios,
  saveSecurityProposal,
} from "@/lib/api";
import { formatMetric } from "@/lib/analytics";

const num = (value: unknown, digits = 2) => new Intl.NumberFormat("en-PK", { maximumFractionDigits: digits }).format(Number(value || 0));
const pct = (value: unknown) => value == null ? "—" : `${Number(value).toFixed(2)}%`;
const signedPct = (value: unknown) => value == null ? "—" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
const title = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());

export default function CompanyPage() {
  const { symbol: raw } = useParams<{ symbol: string }>();
  const symbol = raw.toUpperCase();
  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [research, setResearch] = useState<CompanyResearch | null>(null);
  const [history, setHistory] = useState<MarketPrice[]>([]);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [coverage, setCoverage] = useState<CompanyCompleteness | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    void Promise.all([getCompanyDetail(symbol), getCompanyHistory(symbol), getCompanyResearch(symbol), getPortfolios(), getCompanyCompleteness(symbol).catch(() => null)])
      .then(([company, prices, analysis, portfolioRows, completeness]) => {
        setDetail(company); setHistory(prices); setResearch(analysis); setPortfolios(portfolioRows); setCoverage(completeness);
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, [symbol]);

  useEffect(() => {
    const refreshId = research?.refresh_request_id;
    if (!refreshId) return;
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    const poll = async () => {
      try {
        const refresh = await getContextRefresh(refreshId);
        if (!active) return;
        if (refresh.status === "rebuilt" && refresh.result) {
          setResearch(refresh.result);
          if (timer) clearInterval(timer);
        }
      } catch {
        // The visible degraded result remains honest; a later page load rebuilds lazily.
      }
    };
    timer = setInterval(() => void poll(), 5000);
    void poll();
    return () => {
      active = false;
      if (timer) clearInterval(timer);
      void deactivateContextRefresh(refreshId).catch(() => undefined);
    };
  }, [research?.refresh_request_id]);

  const trajectory = useMemo(() => history.length < 2 ? null : (Number(history.at(-1)?.close) / Number(history[0].close) - 1) * 100, [history]);
  if (loading) return <div className="page-wrap"><div className="panel h-96 skeleton" /></div>;
  if (error || !detail) return <div className="page-wrap"><div className="notice notice-error"><Icon name="warning" />{error || "Company not found"}</div></div>;

  const latest = detail.latest_price;
  const relevance = research?.portfolio_relevance?.[0];
  const marketRisk = (research?.market_research?.risk ?? {}) as Record<string, unknown>;
  const derived = research?.derived_fundamentals;
  const announcements = research?.events.filter(event => event.event_type === "announcement") ?? [];
  const news = research?.events.filter(event => event.event_type === "news") ?? [];
  return <div className="page-wrap">
    <header className="page-heading">
      <div><Link href="/markets" className="eyebrow">Markets / Security research</Link><div className="mt-2 flex flex-wrap items-baseline gap-3"><h1 className="page-title">{symbol}</h1><span className="text-[15px] font-semibold text-[#3f454b]">{detail.company.name}</span></div><p className="page-subtitle">{detail.company.sector} · {detail.company.exchange.code}</p></div>
      {relevance ? <span className="badge badge-good">Held · {pct(Number(relevance.weight) * 100)} portfolio weight</span> : <span className="badge">Not held</span>}
    </header>
    {research?.has_synthetic_data ? <div className="notice notice-warn mb-4" role="alert"><Icon name="warning" /><span><strong>Demo company data.</strong> Seeded fundamentals and documents are clearly marked and must not be treated as observed filings.</span></div> : null}
    <section className="panel mb-4"><div className="panel-head"><div><h2 className="panel-title">Data coverage</h2><p className="mt-1 text-[11px] text-muted">Observed live categories only; demo data does not count.</p></div><span className={`badge ${coverage ? "" : "badge-warn"}`}>{coverage ? "Checked" : "Unavailable"}</span></div>{coverage ? <div className="grid gap-px bg-line sm:grid-cols-3 xl:grid-cols-6"><Coverage label="Price" available={coverage.price.available} note={coverage.price.latest_date}/><Coverage label="History" available={coverage.price.observations > 1} note={`${coverage.price.observations} observations`}/><Coverage label="Fundamentals" available={coverage.fundamentals.available} note={`${coverage.fundamentals.fact_count} facts`}/><Coverage label="Reports" available={coverage.reports.available} note={`${coverage.reports.count} reports`}/><Coverage label="Announcements" available={coverage.announcements.available} note={coverage.announcements.reason}/><Coverage label="News" available={coverage.news.available} note={`${coverage.news.count} linked`}/></div> : <div className="p-4 text-xs text-muted">Coverage diagnostics could not be loaded. Empty sections below are not treated as confirmed absence.</div>}</section>
    <div className="source-rail flex flex-wrap items-end justify-between gap-5 px-6 py-5"><div><p className="metric-label">Last traded price</p><p className="data-font mt-2 text-[36px] font-semibold leading-none tracking-[-.045em]">PKR {latest ? num(latest.close) : "—"}</p></div><div className="sm:text-right"><p className={`data-font text-[17px] font-semibold ${Number(latest?.change_percent) >= 0 ? "positive" : "negative"}`}>{signedPct(latest?.change_percent)}</p><p className="mt-1 text-[11px] text-muted">{latest?.trade_date ?? "Date unavailable"} · {latest?.source ?? "Source unavailable"}</p></div></div>
    <div className="metric-strip mt-4 grid-cols-4"><Metric label="Period trajectory" value={signedPct(trajectory)} /><Metric label="Annual volatility" term="Annual volatility" value={marketRisk.annual_volatility == null ? "—" : pct(Number(marketRisk.annual_volatility) * 100)} /><Metric label="Historical VaR 95" term="Historical VaR 95" value={marketRisk.historical_var_95 == null ? "—" : pct(Number(marketRisk.historical_var_95) * 100)} /><Metric label="Current holding value" value={relevance ? `PKR ${num(relevance.market_value, 0)}` : "Not held"} /></div>
    <DecisionWorkbench symbol={symbol} instrumentId={research?.instrument.id} portfolios={portfolios} />
    <section className="panel mt-4"><div className="panel-head"><h2 className="panel-title">Price history</h2><span className="text-[11px] text-muted">{history.length} daily observations</span></div><div className="panel-body"><LineChart height={260} labels={history.map(row => row.trade_date)} values={history.map(row => Number(row.close))} /></div></section>
    <div className="mt-4 grid gap-4 xl:grid-cols-2">
      <Section title="Reported fundamentals">{research?.fundamentals.length ? <Facts rows={research.fundamentals} /> : <Unavailable text="Normalized exact facts are unavailable. Documentary evidence is not substituted for numeric fundamentals." />}</Section>
      <Section title="Model-derived ratios">{derived && Object.keys(derived.ratios ?? {}).length ? <Facts rows={Object.entries(derived.ratios ?? {}).map(([taxonomy_key, row]) => ({ taxonomy_key, value: String(row.value ?? "—"), unit: "ratio", period_type: "derived", period_end: String(row.period_end ?? "—"), provenance: (row.provenance as { source_name: string | null; is_synthetic: boolean } | undefined) ?? { source_name: null, is_synthetic: false } }))} /> : <Unavailable text={String(derived?.valuation?.reason ?? "Compatible normalized facts are unavailable for deterministic ratios.")} />}</Section>
      <Section title={`Announcements (${announcements.length})`}><CompanyEvents rows={announcements} empty="No stored PSX announcements are linked to this security." /></Section>
      <Section title={`News (${news.length})`}><CompanyEvents rows={news} empty="No stored news stories are linked to this security." /></Section>
      <Section title="Company evidence">{research?.documents.length ? <div className="divider-list">{research.documents.map((document, index) => <article className="py-3 text-[13px]" key={String(document.id ?? index)}><div className="flex items-center gap-2"><strong>{String(document.title)}</strong>{document.is_synthetic ? <span className="badge badge-warn">Demo</span> : null}</div><p className="mt-1 text-[11px] text-muted">{String(document.published_date ?? "Date unavailable")} · {title(String(document.document_type ?? "document"))}</p></article>)}</div> : <Unavailable text="No company documents were returned." />}<Link href={`/research?symbol=${symbol}`} className="btn btn-secondary mt-4">Search cited evidence</Link></Section>
    </div>
  </div>;
}

function Coverage({label,available,note}:{label:string;available:boolean;note?:string|null}){return <div className="bg-white p-3"><div className="flex items-center justify-between gap-2"><strong className="text-[12px]">{label}</strong><span className={`badge ${available?"badge-good":"badge-warn"}`}>{available?"Available":"Missing"}</span></div><p className="mt-2 line-clamp-2 text-[10px] text-muted">{note??(available?"Observed data stored":"No observed data")}</p></div>}

function DecisionWorkbench({ symbol, instrumentId, portfolios }: { symbol: string; instrumentId?: string; portfolios: Portfolio[] }) {
  const [portfolioId, setPortfolioId] = useState(portfolios.find(row => row.is_default)?.id ?? portfolios[0]?.id ?? "");
  const [action, setAction] = useState("add");
  const [sizing, setSizing] = useState("manual");
  const [target, setTarget] = useState("5");
  const [context, setContext] = useState<CompanyResearch | null>(null);
  const [result, setResult] = useState<CandidateEvaluation | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  useEffect(() => { if (!portfolioId && portfolios.length) setPortfolioId(portfolios.find(row => row.is_default)?.id ?? portfolios[0].id); }, [portfolioId, portfolios]);
  useEffect(() => {
    setResult(null); setSavedVersion(null); setContext(null);
    if (portfolioId) void getCompanyResearch(symbol, { portfolioId }).then(value => {
      setContext(value);
      const relevance = value.portfolio_relevance[0];
      setTarget((Number(relevance?.weight ?? 0) * 100 + 5).toFixed(1));
    }).catch((error: Error) => setMessage(error.message));
  }, [symbol, portfolioId]);

  useEffect(() => {
    const refreshId = context?.refresh_request_id;
    if (!refreshId) return;
    let active = true;
    let timer: ReturnType<typeof setInterval> | undefined;
    const poll = async () => {
      try {
        const refresh = await getContextRefresh(refreshId);
        if (!active) return;
        if (refresh.status === "rebuilt" && refresh.result) {
          setContext(refresh.result);
          if (timer) clearInterval(timer);
        }
      } catch {
        // Keep the current receipt visible; returning to the view rebuilds lazily.
      }
    };
    timer = setInterval(() => void poll(), 5000);
    void poll();
    return () => {
      active = false;
      if (timer) clearInterval(timer);
      void deactivateContextRefresh(refreshId).catch(() => undefined);
    };
  }, [context?.refresh_request_id]);

  const relevance = context?.portfolio_relevance[0];
  const sections = context?.context.sections as Record<string, { state?: string; data?: Record<string, unknown> }> | undefined;
  const ips = sections?.ips?.data;
  const terms = ips?.terms as Record<string, unknown> | undefined;
  const macro = sections?.macro?.data;
  const marketRisk = sections?.market_risk?.data;
  const riskMetrics = marketRisk?.risk_metrics as Record<string, unknown> | undefined;
  const currentWeight = Number(relevance?.weight ?? 0) * 100;
  const positionLimit = Number(terms?.max_instrument_weight);
  const positionHeadroom = Number.isFinite(positionLimit) ? Math.max(0, positionLimit * 100 - currentWeight) : null;
  const owned = currentWeight > 0;
  const targetNumber = Number(target);
  const valid = sizing === "optimizer" || action === "remove" || (Number.isFinite(targetNumber) && targetNumber >= 0 && targetNumber <= 100 && (action !== "add" || targetNumber + 1e-6 >= currentWeight) && (action !== "reduce" || (owned && targetNumber <= currentWeight + 1e-6)));
  const payload = () => ({ portfolio_id: portfolioId, action, sizing, target_weight: action === "remove" || sizing === "optimizer" ? null : targetNumber / 100 });

  function chooseAction(next: string) {
    setAction(next); setSizing("manual"); setResult(null); setSavedVersion(null); setMessage("");
    if (next === "add") setTarget((currentWeight + 5).toFixed(1));
    if (next === "reduce") setTarget((currentWeight / 2).toFixed(1));
    if (next === "remove") setTarget("0");
  }
  async function evaluate() {
    setBusy(true); setMessage(""); setSavedVersion(null);
    try { setResult(await evaluateSecurity(symbol, payload())); }
    catch (error) { setMessage(error instanceof Error ? error.message : "Evaluation failed"); }
    finally { setBusy(false); }
  }
  async function save() {
    setBusy(true); setMessage("");
    try {
      const saved = await saveSecurityProposal(symbol, { ...payload(), label: `${title(action)} ${symbol}` });
      setResult(saved.evaluation); setSavedVersion(saved.proposal.version);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Save failed"); }
    finally { setBusy(false); }
  }

  return <section className="panel mt-4">
    <div className="panel-head"><div><h2 className="panel-title">Evaluate for my portfolio</h2><p className="mt-1 text-[11px] text-muted">Creates a proposal for review. Your holdings never change here.</p></div><Link className="btn btn-secondary" href={`/assistant?portfolio_id=${encodeURIComponent(portfolioId)}&instrument_id=${encodeURIComponent(instrumentId ?? "")}&question=${encodeURIComponent(`Does ${symbol} fit my portfolio? What evidence contradicts the case?`)}`}>Ask about {symbol}</Link></div>
    <div className="panel-body grid gap-4">
      {!portfolios.length ? <Unavailable text="Create a portfolio before evaluating a security." /> : <div className="grid gap-3 md:grid-cols-4">
        <label className="field-label">Portfolio<select className="field" value={portfolioId} onChange={event => setPortfolioId(event.target.value)}>{portfolios.map(row => <option value={row.id} key={row.id}>{row.name}</option>)}</select></label>
        <label className="field-label">Action<select className="field" value={action} onChange={event => chooseAction(event.target.value)}><option value="add">Add / increase</option><option value="reduce" disabled={!owned}>Reduce</option><option value="remove" disabled={!owned}>Remove</option></select></label>
        <label className="field-label">Sizing<select className="field" value={sizing} onChange={event => { setSizing(event.target.value); setResult(null); }} disabled={action !== "add"}><option value="manual">Choose target</option><option value="optimizer">Let optimizer size it</option></select></label>
        <label className="field-label">Target portfolio weight{action === "remove" || sizing === "optimizer" ? <input className="field" value={action === "remove" ? "0%" : "Optimizer determined"} disabled /> : <input className="field" type="number" min="0" max="100" step="0.5" value={target} onChange={event => { setTarget(event.target.value); setResult(null); setSavedVersion(null); }} />}</label>
      </div>}
      {relevance ? <><p className="eyebrow">Observed portfolio facts</p><div className="metric-strip grid-cols-4"><Metric label={`Current ${symbol} weight`} value={pct(currentWeight)} /><Metric label="Market value" value={relevance.market_value == null ? "Unavailable" : `PKR ${num(relevance.market_value, 0)}`} /><Metric label="Position headroom" term="Position headroom" value={positionHeadroom == null ? "Not configured" : pct(positionHeadroom)} /><Metric label="IPS state" term="IPS" value={title(String(sections?.ips?.state ?? "not evaluated"))} /></div><p className="eyebrow">Model context</p><div className="metric-strip grid-cols-3"><Metric label="Annual volatility" term="Annual volatility" value={riskMetrics?.annual_volatility == null ? "Unavailable" : pct(Number(riskMetrics.annual_volatility) * 100)} /><Metric label="Marginal risk" term="Risk contribution" value="Evaluate change" /><Metric label="Macro regime" term="Macro regime" value={title(String(macro?.regime ?? "not evaluated"))} /></div></> : null}
      {!valid ? <div className="notice notice-warn"><Icon name="warning" /><span>{action === "add" ? `Choose a target at or above the current ${pct(currentWeight)} weight.` : "Choose a target between 0% and the current weight."}</span></div> : null}
      <div className="flex flex-wrap gap-2"><button className="btn btn-primary" disabled={!portfolioId || busy || !valid} onClick={evaluate}>{busy ? "Evaluating…" : "Evaluate change"}</button>{result ? <button className="btn btn-secondary" disabled={busy} onClick={save}>Save for review</button> : null}</div>
      {message ? <div className="notice notice-error"><Icon name="warning" />{message}</div> : null}
      {savedVersion ? <div className="notice notice-good"><Icon name="check" /><span>Proposal v{savedVersion} saved. Holdings were not changed. <Link className="font-semibold underline" href={`/portfolios/${portfolioId}/build`}>Open proposal review</Link></span></div> : null}
      {Array.isArray(context?.context.deficiencies) && context.context.deficiencies.length ? <div className="notice notice-warn"><Icon name="warning" /><span>{context.context.deficiencies.map(item => String((item as Record<string, unknown>).reason ?? "Requested context is incomplete.")).join(" ")}</span></div> : null}
      {result ? <DecisionResult result={result} /> : null}
    </div>
  </section>;
}

function DecisionResult({ result }: { result: CandidateEvaluation }) {
  const metrics = result.comparison.metrics.filter(row => ["expected_return", "volatility", "sharpe", "beta", "var_95", "es_95", "concentration", "cash_weight"].includes(row.key));
  const currentStress = new Map(result.stress.current.map(row => [String(row.id), row]));
  const riskCurrent = result.comparison.current_risk_contributions[result.candidate.symbol];
  const riskProposed = result.comparison.proposed_risk_contributions[result.candidate.symbol];
  const statusClass = (status: string) => status === "PASS" ? "badge-good" : status === "BREACH" ? "badge-warn" : "";
  const directionLabel = (value: string | undefined) => value === "IMPROVED" ? "Improved" : value === "WORSENED" ? "Deteriorated" : value === "UNCHANGED" ? "No material change" : value === "REFERENCE" ? "Reference" : "Not evaluated";
  return <div className="grid gap-4 border-t border-line pt-4">
    <div className="notice notice-good"><Icon name="check" /><span>{result.decision_explanation.sizing} This is a sandbox comparison; no holding was changed.</span></div>
    <div className="flex flex-wrap gap-2"><span className={`badge ${statusClass(result.comparison.current_compliance.status)}`}>Current <TermLabel term="IPS" />: {title(result.comparison.current_compliance.status.toLowerCase())}</span><span className={`badge ${statusClass(result.comparison.proposed_compliance.status)}`}>Proposed <TermLabel term="IPS" />: {title(result.comparison.proposed_compliance.status.toLowerCase())}</span><span className="badge">{result.candidate.symbol} <TermLabel term="Risk contribution" />: {pct(riskCurrent * 100)} → {pct(riskProposed * 100)}</span></div>
    <div className="table-wrap"><table className="data-table"><thead><tr><th>Portfolio metric</th><th>Current</th><th>Proposed</th><th>Assessment</th></tr></thead><tbody>{metrics.map(row => <tr key={row.key}><td className="font-semibold"><span className="inline-flex items-center gap-1">{row.label}<TermHelp term={row.label} /></span></td><td className="data-font">{formatMetric(row.current, row.unit)}</td><td className="data-font">{formatMetric(row.proposed, row.unit)}</td><td><span className={`badge ${row.classification === "IMPROVED" ? "badge-good" : row.classification === "WORSENED" ? "badge-warn" : ""}`}>{directionLabel(row.classification)}</span></td></tr>)}</tbody></table></div>
    <div><p className="eyebrow mb-2">Current vs proposed stress</p><div className="table-wrap"><table className="data-table"><thead><tr><th>Scenario</th><th>Current</th><th>Proposed</th><th>Proposed IPS</th></tr></thead><tbody>{result.stress.proposed.map((row, index) => { const before = currentStress.get(String(row.id)); const beforeReturn = Number(before?.return ?? 0); const proposedReturn = Number(row.return); const compliance = row.compliance as Record<string, unknown>; const status = String(compliance?.status ?? "NOT_EVALUATED"); return <tr key={String(row.id ?? index)}><td className="font-semibold">{String(row.name)}</td><td className={`data-font ${beforeReturn < 0 ? "negative" : "positive"}`}>{signedPct(beforeReturn * 100)}</td><td className={`data-font ${proposedReturn < 0 ? "negative" : "positive"}`}>{signedPct(proposedReturn * 100)}</td><td><span className={`badge ${statusClass(status)}`}>{title(status.toLowerCase())}</span></td></tr>; })}</tbody></table></div></div>
    <div className="grid gap-3 md:grid-cols-2"><DecisionChanges title="What improved" rows={result.decision_explanation.improved} empty="No modeled metric materially improved." tone="good" /><DecisionChanges title="What deteriorated" rows={result.decision_explanation.deteriorated} empty="No modeled metric materially deteriorated." tone="warn" /></div>
    <details><summary className="cursor-pointer text-[11px] font-semibold text-accent">Assumptions and method</summary><p className="mt-2 text-[12px] leading-5 text-muted">{String(result.decision_explanation.assumptions.candidate_construction ?? "Candidate construction method is recorded with the proposal.")} Metrics use aligned canonical prices through {String(result.comparison.data_cutoff)}.</p></details>
  </div>;
}

function DecisionChanges({ title: heading, rows, empty, tone }: { title: string; rows: Array<Record<string, unknown>>; empty: string; tone: "good" | "warn" }) {
  return <div className="source-rail p-4"><p className="metric-label">{heading}</p>{rows.length ? <ul className="mt-2 space-y-1 text-[12px]">{rows.slice(0, 4).map((row, index) => <li key={index} className={tone === "good" ? "positive" : "negative"}>{String(row.label)}</li>)}</ul> : <p className="mt-2 text-[12px] text-muted">{empty}</p>}</div>;
}

function Facts({ rows }: { rows: Array<{ taxonomy_key: string; value: string | number; unit: string; period_type: string; period_end: string; provenance?: { source_name: string | null; is_synthetic: boolean } }> }) {
  const display = (row: { value: string | number; unit: string }) => row.unit === "ratio" ? pct(Number(row.value) * 100) : `${num(row.value)} ${row.unit}`;
  return <div className="table-wrap"><table className="data-table"><thead><tr><th>Fact</th><th>Value</th><th>Period</th><th>Basis</th><th>Source</th></tr></thead><tbody>{rows.slice(0, 8).map((row, index) => <tr key={`${row.taxonomy_key}-${row.period_end}-${index}`}><td className="font-semibold">{title(row.taxonomy_key)}</td><td className="data-font">{display(row)}</td><td>{row.period_end}</td><td>{title(row.period_type)}</td><td>{row.provenance?.is_synthetic ? <span className="badge badge-warn">Demo data</span> : row.provenance?.source_name ? <span className="text-[11px] text-muted">{row.provenance.source_name}</span> : <span className="text-[11px] text-muted">Unavailable</span>}</td></tr>)}</tbody></table></div>;
}

function CompanyEvents({ rows, empty }: { rows: CompanyResearch["events"]; empty: string }) {
  if (!rows.length) return <Unavailable text={empty} />;
  return <div className="divider-list">{rows.map(event => <article className="py-3 text-[13px]" key={event.id}>
    <strong>{event.title}</strong>
    <p className="mt-1 text-[11px] text-muted">{event.occurred_at ? new Date(event.occurred_at).toLocaleDateString("en-PK") : "Date unavailable"}</p>
    <div className="mt-2 flex flex-wrap gap-2">{event.sources.map(source => <a className="text-[11px] font-semibold text-accent hover:underline" href={source.source_url} target="_blank" rel="noreferrer" key={`${event.id}-${source.source_url}`}>{source.source_name}</a>)}</div>
  </article>)}</div>;
}

function Metric({ label, value, term }: { label: string; value: string; term?: string }) { return <div className="metric"><p className="metric-label inline-flex items-center gap-1">{label}{term ? <TermHelp term={term} /> : null}</p><p className="metric-value data-font">{value}</p></div>; }
function Section({ title: heading, children }: { title: string; children: React.ReactNode }) { return <section className="panel"><div className="panel-head"><h2 className="panel-title">{heading}</h2></div><div className="panel-body">{children}</div></section>; }
function Unavailable({ text }: { text: string }) { return <div className="flex gap-2 text-xs text-muted"><Icon name="clock" size={15} />{text}</div>; }
