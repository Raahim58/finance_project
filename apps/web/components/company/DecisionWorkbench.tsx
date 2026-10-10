"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
import { Icon } from "@/components/Icon";
import { TermHelp, TermLabel } from "@/components/TermHelp";
import { CandidateEvaluation, CompanyResearch, Portfolio, evaluateSecurity, getCompanyResearch, getContextRefresh, deactivateContextRefresh, saveSecurityProposal } from "@/lib/api";
import { formatMetric } from "@/lib/analytics";
import styles from "./DecisionWorkbench.module.css";
import { formatNumber } from "@/lib/overview";
const num = formatNumber;
const pct = (value: unknown) => value == null ? "—" : `${Number(value).toFixed(2)}%`;
const signedPct = (value: unknown) => value == null ? "—" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
const title = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
export function DecisionWorkbench({ symbol, instrumentId, portfolios, selectedPortfolioId }: { symbol: string; instrumentId?: string; portfolios: Portfolio[]; selectedPortfolioId: string }) {
  const [portfolioId, setPortfolioId] = useState(selectedPortfolioId);
  const [action, setAction] = useState("add");
  const [sizing, setSizing] = useState("manual");
  const [target, setTarget] = useState("5");
  const [context, setContext] = useState<CompanyResearch | null>(null);
  const [result, setResult] = useState<CandidateEvaluation | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [savedVersion, setSavedVersion] = useState<number | null>(null);

  useEffect(() => { setPortfolioId(selectedPortfolioId); }, [selectedPortfolioId]);
  useEffect(() => {
    setResult(null); setSavedVersion(null); setContext(null);
    if (portfolioId) void getCompanyResearch(symbol, { portfolioId, displayOnly:true }).then(value => {
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

  const workspace = useAssistantWorkspace();
  const fixed = action === "remove" || sizing === "optimizer";
  return <section className={styles.wrap}>
    <div className={styles.head}><div><h2>Evaluate for my portfolio</h2><p>Compares your portfolio with and without this change using stored data. Your holdings never change here.</p></div>{workspace ? <button className={styles.link} onClick={() => workspace.askNew(`Does ${symbol} fit my portfolio? What evidence contradicts the case?`)}>Ask about {symbol} in chat →</button> : null}</div>
    {!portfolios.length ? <p className={styles.note}>Create a portfolio before evaluating a security.</p> : <div className={styles.controls}>
      <label>Portfolio<select value={portfolioId} onChange={event => setPortfolioId(event.target.value)}><option value="">Select a portfolio</option>{portfolios.map(row => <option value={row.id} key={row.id}>{row.name}</option>)}</select></label>
      <label>Action<select value={action} onChange={event => chooseAction(event.target.value)}><option value="add">Add / increase</option><option value="reduce" disabled={!owned}>Reduce</option><option value="remove" disabled={!owned}>Remove</option></select></label>
      <label>Sizing<select value={sizing} onChange={event => { setSizing(event.target.value); setResult(null); }} disabled={action !== "add"}><option value="manual">Choose target</option><option value="optimizer">Let optimizer size it</option></select></label>
      <label>Target weight (%){fixed ? <input value={action === "remove" ? "0" : "Optimizer sets it"} disabled /> : <input type="number" min="0" max="100" step="0.5" value={target} onChange={event => { setTarget(event.target.value); setResult(null); setSavedVersion(null); }} />}</label>
    </div>}
    {relevance ? <dl className={styles.facts}>
      <Fact label={`Current ${symbol} weight`} value={pct(currentWeight)} />
      <Fact label="Market value" value={relevance.market_value == null ? "Unavailable" : `PKR ${num(relevance.market_value, 0)}`} />
      <Fact label="Position headroom" term="Position headroom" value={positionHeadroom == null ? "Not configured" : pct(positionHeadroom)} />
      <Fact label="IPS state" term="IPS" value={title(String(sections?.ips?.state ?? "not evaluated"))} />
      <Fact label="Annual volatility" term="Annual volatility" value={riskMetrics?.annual_volatility == null ? "Unavailable" : pct(Number(riskMetrics.annual_volatility) * 100)} />
      <Fact label="Macro regime" term="Macro regime" value={title(String(macro?.regime ?? "not evaluated"))} />
    </dl> : null}
    {!valid ? <p className={`${styles.note} ${styles.warn}`}>{action === "add" ? `Choose a target at or above the current ${pct(currentWeight)} weight.` : "Choose a target between 0% and the current weight."}</p> : null}
    <div className={styles.bar}><button className="btn btn-primary" disabled={!portfolioId || busy || !valid} onClick={evaluate}>{busy ? "Evaluating…" : "Evaluate change"}</button>{result ? <button className="btn btn-secondary" disabled={busy} onClick={save}>Save for review</button> : null}</div>
    {message ? <p className={`${styles.note} ${styles.err}`}>{message}</p> : null}
    {savedVersion ? <p className={`${styles.note} ${styles.good}`}>Proposal v{savedVersion} saved; holdings were not changed. <Link className="underline" href={`/portfolios/${portfolioId}/build`}>Open proposal review</Link></p> : null}
    {!result && Array.isArray(context?.context.deficiencies) && context.context.deficiencies.length ? <p className={styles.note}>{context.context.deficiencies.map(item => String((item as Record<string, unknown>).reason ?? "Requested context is incomplete.")).join(" ")}</p> : null}
    {result ? <DecisionResult result={result} /> : null}
  </section>;
}

function Fact({ label, value, term }: { label: string; value: string; term?: string }) { return <div><dt>{label}{term ? <TermHelp term={term} /> : null}</dt><dd>{value}</dd></div>; }

function DecisionResult({ result }: { result: CandidateEvaluation }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [result]);
  const metrics = result.comparison.metrics.filter(row => ["expected_return", "volatility", "sharpe", "beta", "var_95", "es_95", "concentration", "cash_weight"].includes(row.key));
  const currentStress = new Map(result.stress.current.map(row => [String(row.id), row]));
  const riskCurrent = result.comparison.current_risk_contributions[result.candidate.symbol];
  const riskProposed = result.comparison.proposed_risk_contributions[result.candidate.symbol];
  const tone = (status: string) => status === "PASS" ? styles.good : status === "BREACH" ? styles.warn : "";
  const directionLabel = (value: string | undefined) => value === "IMPROVED" ? "Improved" : value === "WORSENED" ? "Deteriorated" : value === "UNCHANGED" ? "No material change" : value === "REFERENCE" ? "Reference" : "Not evaluated";
  const directionTone = (value: string | undefined) => value === "IMPROVED" ? styles.good : value === "WORSENED" ? styles.warn : "";
  const list = (rows: Array<Record<string, unknown>>, empty: string) => rows.length ? <ul>{rows.slice(0, 4).map((row, index) => <li key={index}>{String(row.label)}</li>)}</ul> : <p className={styles.note} style={{ margin: 0 }}>{empty}</p>;
  return <div className={styles.result} ref={ref}>
    <h3>Result</h3>
    <p className={styles.note} style={{ margin: "0 0 10px" }}>{result.decision_explanation.sizing} Sandbox comparison only.</p>
    <p className={styles.verdict}>
      <span>Current <TermLabel term="IPS" />: <b className={tone(result.comparison.current_compliance.status)}>{title(result.comparison.current_compliance.status.toLowerCase())}</b></span>
      <span>Proposed <TermLabel term="IPS" />: <b className={tone(result.comparison.proposed_compliance.status)}>{title(result.comparison.proposed_compliance.status.toLowerCase())}</b></span>
      <span>{result.candidate.symbol} <TermLabel term="Risk contribution" />: {pct(riskCurrent * 100)} to {pct(riskProposed * 100)}</span>
    </p>
    <table className={styles.table}><thead><tr><th>Portfolio metric</th><th>Current</th><th>Proposed</th><th>Assessment</th></tr></thead><tbody>{metrics.map(row => <tr key={row.key}><td><span className="inline-flex items-center gap-1">{row.label}<TermHelp term={row.label} /></span></td><td>{formatMetric(row.current, row.unit)}</td><td>{formatMetric(row.proposed, row.unit)}</td><td className={directionTone(row.classification)}>{directionLabel(row.classification)}</td></tr>)}</tbody></table>
    <table className={styles.table}><thead><tr><th>Stress scenario</th><th>Current</th><th>Proposed</th><th>Proposed IPS</th></tr></thead><tbody>{result.stress.proposed.map((row, index) => { const beforeReturn = Number(currentStress.get(String(row.id))?.return ?? 0); const proposedReturn = Number(row.return); const status = String((row.compliance as Record<string, unknown>)?.status ?? "NOT_EVALUATED"); return <tr key={String(row.id ?? index)}><td>{String(row.name)}</td><td className={beforeReturn < 0 ? "negative" : "positive"}>{signedPct(beforeReturn * 100)}</td><td className={proposedReturn < 0 ? "negative" : "positive"}>{signedPct(proposedReturn * 100)}</td><td className={tone(status)}>{title(status.toLowerCase())}</td></tr>; })}</tbody></table>
    <div className={styles.changes}><div><h4>What improved</h4>{list(result.decision_explanation.improved, "No modeled metric materially improved.")}</div><div><h4>What deteriorated</h4>{list(result.decision_explanation.deteriorated, "No modeled metric materially deteriorated.")}</div></div>
    <details className={styles.details}><summary>Assumptions and method</summary><p>{String(result.decision_explanation.assumptions.candidate_construction ?? "Candidate construction method is recorded with the proposal.")} Metrics use aligned canonical prices through {String(result.comparison.data_cutoff)}.</p></details>
  </div>;
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
