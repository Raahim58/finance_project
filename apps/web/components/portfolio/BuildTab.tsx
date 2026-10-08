"use client";

import Link from "next/link";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { ComparisonTable } from "@/components/DecisionTables";
import { CompanyLogo } from "@/components/markets/CompanyLogo";
import styles from "@/components/portfolio/build/build.module.css";
import type { WorkspaceData } from "@/components/workspace/useWorkspaceData";
import { PortfolioComparison, comparePortfolio, createAllocation, decideRecommendation, runOptimizer } from "@/lib/api";
import { BuildExtras, getBuildExtras } from "@/lib/api/portfolio-build";
import { normalizeWeights, weightSummary } from "@/lib/analytics";
import { formatDate, formatNumber, humanize, numeric } from "@/lib/overview";
import { buildInsights, buildRows, ipsFit, labelFor, metricOf, objectiveOptions, objectivesNeedingReturns, returnMethodOptions, sectorSegments } from "@/lib/portfolio-build";

const SECTOR_COLORS = ["#278df5", "#55acff", "#7fc6ff", "#afdafe", "#c8e7ff"];
const OTHERS_COLOR = "#d4d8de";
const DEFAULT_OBJECTIVE = "target_return_minimum_variance";
const DEFAULT_METHOD = "historical_shrunk";

const pctOf = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(digits)}%`;
const signedPp = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? "" : `${value > 0 ? "+" : value < 0 ? "-" : ""}${Math.abs(value * 100).toFixed(digits)}%`;
const tone = (value: number | null | undefined, goodWhenPositive = true) => value == null || Math.abs(value) < 1e-9 ? "" : (value > 0) === goodWhenPositive ? styles.pos : styles.neg;
const constraintPct = (value: unknown) => { const n = numeric(value); return n == null ? "Not set" : pctOf(n, 1); };

export function BuildTab({ portfolioId, data, setMessage }: { portfolioId: string; data: WorkspaceData; setMessage: (message: string) => void }) {
  const assistant = useAssistantWorkspace();
  const [question, setQuestion] = useState("");
  const [selectedAllocationId, setSelectedAllocationId] = useState("");
  const hydratedAllocation = useRef("");
  const savedAllocations = useMemo(() => [...data.allocations].filter(row => ["optimized", "sandbox"].includes(row.kind)).sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)), [data.allocations]);
  const savedAllocation = savedAllocations.find(row => row.id === selectedAllocationId) ?? savedAllocations[0] ?? null;
  const [dirty, setDirty] = useState(false);
  const recommendationId = useSearchParams().get("recommendation");
  const summary = data.summary;
  const confirmed = data.ips.find(row => row.status === "confirmed");
  const current = useMemo(() => {
    const total = Number(summary?.total_value ?? 0);
    const weights: Record<string, number> = Object.fromEntries((summary?.holdings ?? []).map(row => [row.symbol, total ? Number(row.market_value) / total : 0]));
    if (total && Number(summary?.cash_balance ?? 0) > 0) weights.CASH = Number(summary?.cash_balance) / total;
    return weights;
  }, [summary]);
  const [proposed, setProposed] = useState<Record<string, number>>(current);
  const [objective, setObjective] = useState(DEFAULT_OBJECTIVE);
  const [method, setMethod] = useState(DEFAULT_METHOD);
  const [analystReturns, setAnalystReturns] = useState<Record<string, string>>({});
  const [targetVolatility, setTargetVolatility] = useState("");
  const [targetBeta, setTargetBeta] = useState("");
  const [running, setRunning] = useState(false);
  const [comparison, setComparison] = useState<PortfolioComparison | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [extras, setExtras] = useState<BuildExtras | null>(null);
  const [extrasError, setExtrasError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  useEffect(() => {
    if (dirty) return;
    if (savedAllocation && hydratedAllocation.current !== savedAllocation.id) {
      hydratedAllocation.current = savedAllocation.id;
      setProposed(Object.fromEntries(savedAllocation.items.map(item => [item.is_cash ? "CASH" : item.symbol, Number(item.target_weight)])));
      setComparison(null);
    } else if (!savedAllocation) setProposed(current);
  }, [current, savedAllocation, dirty]);

  // Sector mix, names, websites and drawdown come from a DB-backed endpoint, refreshed after each comparison.
  const comparedWeights = comparison?.proposed_weights ?? null;
  useEffect(() => {
    let active = true;
    setExtrasError(null);
    getBuildExtras(portfolioId, comparedWeights).then(value => active && setExtras(value)).catch((error: Error) => { if (active) { setExtras(null); setExtrasError(error.message); } });
    return () => { active = false; };
  }, [portfolioId, comparedWeights]);

  const weightState = weightSummary(proposed);
  const usesReturns = objectivesNeedingReturns.includes(objective);
  const riskySymbols = Object.keys(current).filter(symbol => symbol !== "CASH");
  const compatibilityProblem = objective === "target_return_minimum_variance" && confirmed?.required_return == null ? "Required-return construction needs a calculable target in the confirmed IPS."
    : objective === "target_beta" && !confirmed?.constraints.capm_market_proxy_symbol ? "Target beta requires an approved broad-index CAPM market proxy in the IPS."
    : objective === "risk_budget" && !confirmed?.constraints.risk_budgets ? "Custom risk budget requires security-level IPS risk budgets."
    : ["risk_parity", "risk_budget"].includes(objective) && confirmed?.constraints.min_cash_weight == null ? "Risk-budget objectives require a confirmed minimum cash weight."
    : objective === "max_sharpe" && !data.assumptions?.risk_free ? "Maximum Sharpe requires an observed or explicit risk-free series."
    : !confirmed ? "No confirmed IPS: constraints cannot be applied or verified."
    : null;
  const analystIncomplete = usesReturns && method === "user_model" && riskySymbols.some(symbol => !Number.isFinite(Number(analystReturns[symbol])) || (analystReturns[symbol] ?? "").trim() === "");

  const instruments = useMemo(() => new Map((extras?.instruments ?? []).map(row => [row.symbol, row])), [extras]);
  const nameOf = (symbol: string) => symbol === "CASH" ? "Cash" : summary?.holdings.find(row => row.symbol === symbol)?.name ?? instruments.get(symbol)?.name ?? "";
  const rowsView = buildRows(current, proposed, showAll ? null : 10);
  // Fallback when the extras endpoint is unavailable: sectors already stored on the holdings.
  const holdingSectorWeights = useMemo(() => {
    const out: Record<string, number> = {};
    for (const row of summary?.holdings ?? []) if (current[row.symbol] > 0) out[row.sector || "Unclassified"] = (out[row.sector || "Unclassified"] ?? 0) + current[row.symbol];
    if (current.CASH > 0) out.Cash = current.CASH;
    return out;
  }, [summary, current]);
  const fitCurrent = comparison ? ipsFit(comparison.current_compliance) : null;
  const fitProposed = comparison ? ipsFit(comparison.proposed_compliance) : null;
  const insights = buildInsights(comparison, buildRows(current, proposed, null).rows, fitProposed);

  async function analyze(weights = proposed) {
    const state = weightSummary(weights);
    if (!state.valid) { setMessage(`Proposed weights must total 100%. Submitted ${(state.submittedSum * 100).toFixed(6)}%; residual ${(state.residual * 100).toFixed(6)} percentage points.`); return; }
    setRunning(true);
    try { setComparison(await comparePortfolio(portfolioId, weights, "Manual sandbox")); } catch (error) { setMessage(error instanceof Error ? error.message : "Comparison failed"); } finally { setRunning(false); }
  }
  async function optimize() {
    if (compatibilityProblem) { setMessage(compatibilityProblem); return; }
    setRunning(true); setMessage("");
    try {
      const result = await runOptimizer(portfolioId, {
        objective,
        expected_return_method: usesReturns ? method : null,
        expected_return_assumptions: usesReturns && method === "user_model" ? Object.fromEntries(Object.entries(analystReturns).map(([symbol, value]) => [symbol, Number(value) / 100])) : null,
        target_return: objective === "target_return_minimum_variance" ? confirmed?.required_return : null,
        target_volatility: objective === "target_volatility_maximum_return" ? Number(targetVolatility) / 100 : null,
        target_beta: objective === "target_beta" ? Number(targetBeta) : null,
      });
      setDiagnostics(result.diagnostics);
      if (result.status !== "optimal") { setMessage(`Optimizer returned ${result.status}. ${String(result.diagnostics.reason ?? "")}`); return; }
      setDirty(true); setProposed(result.weights);
      setComparison(await comparePortfolio(portfolioId, result.weights, "Optimized proposal"));
      setMessage(`Optimized proposal saved as allocation ${result.allocation_set_id}. No trades were placed.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Optimization failed"); } finally { setRunning(false); }
  }
  async function saveSandbox() {
    setRunning(true);
    try {
      const allocation = await createAllocation(portfolioId, {
        kind: "sandbox", base_value: Number(summary?.total_value ?? 0),
        assumptions: { source: "manual_build_workspace", compliance_snapshot: comparison?.proposed_compliance ?? null, ...(recommendationId ? { recommendation_id: recommendationId } : {}) },
        items: Object.entries(proposed).filter(([, weight]) => weight > 0).map(([symbol, weight]) => ({ symbol, target_weight: weight, locked: false, is_cash: symbol === "CASH" })),
      });
      if (recommendationId) await decideRecommendation(recommendationId, "reviewed");
      setMessage(`Sandbox allocation v${allocation.version} saved${recommendationId ? " and linked to the recommendation" : ""}. Actual holdings were not changed.`);
    } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save sandbox"); } finally { setRunning(false); }
  }
  function reset() { setObjective(DEFAULT_OBJECTIVE); setMethod(DEFAULT_METHOD); setTargetVolatility(""); setTargetBeta(""); setAnalystReturns({}); setDirty(true); setProposed(current); setComparison(null); setDiagnostics(null); }
  const setWeight = (symbol: string, percent: string) => { setDirty(true); setComparison(null); setProposed(values => ({ ...values, [symbol]: Math.max(0, Number(percent) || 0) / 100 })); };

  if (!summary) return <div className={styles.empty}>Loading portfolio holdings…</div>;
  if (!Object.keys(current).length) return <div className={styles.empty}>This portfolio has no holdings or cash, so there is nothing to optimize. Add holdings on the Overview tab first.</div>;

  const c = confirmed?.constraints;
  const mandate: Array<[string, string]> = [
    ["Required return", constraintPct(confirmed?.required_return)],
    ["Volatility ceiling", constraintPct(c?.target_volatility)],
    ["Beta ceiling", numeric(c?.target_beta) == null ? "Not set" : String(c?.target_beta)],
    ["Max security weight", constraintPct(c?.max_instrument_weight)],
    ["Min cash", constraintPct(c?.min_cash_weight)],
    ["Max cash", constraintPct(c?.max_cash_weight)],
    ["Max sector weight", typeof c?.max_sector_weight === "object" && c?.max_sector_weight ? "Per-sector limits" : constraintPct(c?.max_sector_weight)],
    ["Benchmark", String(c?.benchmark_symbol ?? "Not set")],
  ];
  const ddCurrent = extras?.max_drawdown.current ?? null, ddProposed = extras?.max_drawdown.proposed ?? null;
  const metricRows: Array<{ key: string; head: string; sub: string; cur: string; pro: string; delta: string; deltaTone: string }> = (() => {
    const fromMetric = (key: string, head: string, sub: string, kind: "pct" | "ratio") => {
      const m = metricOf(comparison, key); const cv = numeric(m?.current), pv = numeric(m?.proposed), d = cv != null && pv != null ? pv - cv : null;
      const good = m?.classification === "IMPROVED" ? styles.pos : m?.classification === "WORSENED" ? styles.neg : "";
      return { key, head, sub, cur: kind === "pct" ? pctOf(cv) : formatNumber(cv, 2), pro: kind === "pct" ? pctOf(pv) : formatNumber(pv, 2), delta: d == null ? "" : kind === "pct" ? `${d > 0 ? "+" : ""}${(d * 100).toFixed(1)} pp` : `${d > 0 ? "+" : ""}${d.toFixed(2)}`, deltaTone: good };
    };
    const dd = ddCurrent != null && ddProposed != null ? ddProposed - ddCurrent : null;
    const fit = fitCurrent && fitProposed && fitCurrent.ratio != null && fitProposed.ratio != null ? fitProposed.ratio - fitCurrent.ratio : null;
    return [
      fromMetric("expected_return", "Expected return", "model-based", "pct"),
      fromMetric("volatility", "Volatility", "annualized", "pct"),
      { key: "max_drawdown", head: "Max drawdown", sub: "historical, constant weights", cur: pctOf(ddCurrent), pro: pctOf(ddProposed), delta: dd == null ? "" : `${dd > 0 ? "+" : ""}${(dd * 100).toFixed(1)} pp`, deltaTone: tone(dd) },
      fromMetric("beta", "Beta", `vs ${String(confirmed?.constraints.benchmark_symbol ?? "benchmark")}`, "ratio"),
      fromMetric("sharpe", "Sharpe ratio", "model-based", "ratio"),
      { key: "ips_fit", head: "IPS fit", sub: "evaluated checks passed", cur: fitCurrent?.ratio == null ? "—" : `${pctOf(fitCurrent.ratio, 0)} (${fitCurrent.passed}/${fitCurrent.evaluated})`, pro: fitProposed?.ratio == null ? "—" : `${pctOf(fitProposed.ratio, 0)} (${fitProposed.passed}/${fitProposed.evaluated})`, delta: fit == null ? "" : `${fit > 0 ? "+" : ""}${(fit * 100).toFixed(0)} pp`, deltaTone: tone(fit) },
    ];
  })();

  const renderRow = (row: { symbol: string; current: number; proposed: number; delta: number }, index: number, side: "current" | "proposed") => {
    const info = instruments.get(row.symbol);
    const value = side === "current" ? row.current : row.proposed;
    return <tr key={`${side}-${row.symbol}`}>
      <td className={styles.rank}>{index + 1}</td>
      <td><span className={styles.sym}>{row.symbol === "CASH" ? null : <CompanyLogo symbol={row.symbol} website={info?.official_website} size={22} />}{row.symbol === "CASH" ? "Cash" : row.symbol}</span></td>

      {side === "current" ? <>
        <td className={styles.num}>{pctOf(value)}</td>
        <td className={styles.barCell}><div className={styles.bar}><span style={{ width: `${Math.min(100, value * 100)}%` }} /></div></td>
      </> : <>
        <td className={styles.num}><input className={styles.weightInput} aria-label={`${row.symbol} proposed percent`} type="number" min="0" max="100" step="0.1" value={Number((value * 100).toFixed(2))} onChange={event => setWeight(row.symbol, event.target.value)} /></td>
        <td className={`${styles.barCell}`}><div className={`${styles.bar} ${styles.barProposed}`}><span style={{ width: `${Math.min(100, value * 100)}%` }} /></div></td>
        <td className={`${styles.num} ${tone(row.delta)}`}>{Math.abs(row.delta) < 0.00005 ? "0.00" : `${row.delta > 0 ? "+" : ""}${(row.delta * 100).toFixed(2)}`}</td>
      </>}
    </tr>;
  };
  const othersRow = (side: "current" | "proposed") => rowsView.others ? <tr key={`o-${side}`}>
    <td /><td><strong>Others</strong></td>
    <td className={styles.num}>{pctOf(side === "current" ? rowsView.others.current : rowsView.others.proposed)}</td>
    <td className={styles.barCell}><div className={`${styles.bar} ${side === "proposed" ? styles.barProposed : ""}`}><span style={{ width: `${Math.min(100, (side === "current" ? rowsView.others.current : rowsView.others.proposed) * 100)}%` }} /></div></td>
    {side === "proposed" ? <td className={`${styles.num} ${tone(rowsView.others.delta)}`}>{signedPp(rowsView.others.delta)}</td> : null}
  </tr> : null;

  const allocationBar = (title: string, weights: Record<string, number> | null | undefined) => {
    const segments = sectorSegments(weights);
    return <div>
      <h3 className={styles.h3}>{title}</h3>
      {segments.length ? <>
        <div className={styles.stack}>{segments.map((segment, index) => <span key={segment.label} title={`${segment.label} ${pctOf(segment.value)}`} style={{ width: `${segment.value * 100}%`, background: segment.label === "Cash" ? "#a8a8a8" : segment.label === "Others" ? OTHERS_COLOR : SECTOR_COLORS[index % SECTOR_COLORS.length] }} />)}</div>
        <div className={styles.legend}>{segments.map((segment, index) => <span key={segment.label}><i className={styles.dot} style={{ background: segment.label === "Cash" ? "#a8a8a8" : segment.label === "Others" ? OTHERS_COLOR : SECTOR_COLORS[index % SECTOR_COLORS.length] }} />{segment.label} {pctOf(segment.value)}</span>)}</div>
      </> : <p className={styles.empty}>Sector mix unavailable.</p>}
    </div>;
  };

  const missingTarget = objective === "target_volatility_maximum_return" ? !targetVolatility || Number(targetVolatility) <= 0 : objective === "target_beta" ? !targetBeta || !Number.isFinite(Number(targetBeta)) : false;
  const proposalStatus = !comparison ? "Not evaluated" : fitProposed?.notEvaluated || comparison.proposed_compliance.status === "BREACH" ? `${(fitProposed?.evaluated ?? 0) - (fitProposed?.passed ?? 0)} breach · ${fitProposed?.notEvaluated ?? 0} check unavailable` : comparison.proposed_compliance.status === "PASS" ? "Evaluated checks passed" : "Not evaluated";
  return <div className={styles.root}>
    <main data-portfolio-panel="content" className={styles.main}>
      <h1 className={styles.title}>{savedAllocation && !dirty ? `Saved proposal · ${formatDate(savedAllocation.created_at)}` : "Portfolio construction"}</h1>
      <div className={styles.toolbar}>
        <label className={styles.control}>Objective<select id="build-objective" className={styles.field} value={objective} onChange={event => setObjective(event.target.value)}>{objectiveOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <label className={styles.control}>Method<select id="build-method" className={styles.field} value={method} disabled={!usesReturns} onChange={event => setMethod(event.target.value)}>{returnMethodOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        <button type="button" className={styles.btn} disabled={running || !weightState.valid} onClick={() => void analyze()}>{running ? "Calculating…" : savedAllocation && !dirty ? "Compare saved proposal" : "Compare proposal"}</button>
        <button type="button" className={styles.btnSmall} disabled={running || !weightState.valid} onClick={saveSandbox}>Save sandbox</button>
        <details className={styles.actions}><summary aria-label="Construction actions">•••</summary><button type="button" disabled={running || Boolean(compatibilityProblem) || analystIncomplete || missingTarget} onClick={optimize}>Run optimization</button><button type="button" disabled={running} onClick={reset}>Reset to current holdings</button></details>
      </div>
      <p className={styles.sub}>Proposal only · holdings and transactions remain unchanged. Comparison uses current stored market inputs; configuration controls apply to a new optimizer run.</p>
      {savedAllocations.length > 1 ? <label className={styles.saved}>Saved proposal<select className={styles.field} value={savedAllocation?.id ?? ""} onChange={event => {setDirty(false); hydratedAllocation.current = ""; setSelectedAllocationId(event.target.value);}}>{savedAllocations.map(row => <option key={row.id} value={row.id}>{humanize(row.kind)} v{row.version} · {formatDate(row.created_at)}</option>)}</select></label> : null}
      {summary.valuation_complete === false ? <div className={styles.noticeBad}>{summary.valuation_note ?? `Missing prices: ${summary.unpriced_symbols.join(", ")}`}</div> : null}
      {compatibilityProblem ? <p className={styles.notice}>{compatibilityProblem}</p> : null}
      {objective === "target_volatility_maximum_return" ? <label className={styles.saved}>Target volatility (%)<input className={styles.field} type="number" min="0.1" step="0.1" value={targetVolatility} onChange={event => setTargetVolatility(event.target.value)} /></label> : null}
      {objective === "target_beta" ? <label className={styles.saved}>Target beta<input className={styles.field} type="number" step="0.05" value={targetBeta} onChange={event => setTargetBeta(event.target.value)} /></label> : null}
      {usesReturns && method === "user_model" ? <div className={styles.analyst}>{riskySymbols.map(symbol => <label key={symbol}>{symbol} annual return (%)<input type="number" step="0.1" value={analystReturns[symbol] ?? ""} onChange={event => setAnalystReturns(values => ({ ...values, [symbol]: event.target.value }))} /></label>)}</div> : null}
      <div className={styles.allocations}>
        <section><div className={styles.allocationHeading}><h2>Current allocation</h2><span>Total {pctOf(Object.values(current).reduce((sum, value) => sum + value, 0))}</span></div>
          <table className={styles.table}><thead><tr><th>#</th><th>Company</th><th className={styles.num}>Weight</th><th /></tr></thead><tbody>{rowsView.rows.map((row,index) => renderRow(row,index,"current"))}{othersRow("current")}</tbody></table>
          {allocationBar("Sector allocation", extras?.sector_weights.current ?? holdingSectorWeights)}
        </section>
        <section><div className={styles.allocationHeading}><h2>Proposed allocation</h2><span className={weightState.valid ? "" : styles.neg}>Total {pctOf(weightState.submittedSum)}</span></div>
          <table className={styles.table}><thead><tr><th>#</th><th>Company</th><th className={styles.num}>Weight %</th><th /><th className={styles.num}>Δ pp</th></tr></thead><tbody>{rowsView.rows.map((row,index) => renderRow(row,index,"proposed"))}{othersRow("proposed")}</tbody></table>
          {allocationBar("Sector allocation", comparison ? extras?.sector_weights.proposed : null)}
        </section>
      </div>
      <div className={styles.btnRow}>{buildRows(current, proposed, null).rows.length > 10 ? <button type="button" className={styles.btnSmall} onClick={() => setShowAll(value => !value)}>{showAll ? "Show top 10" : "Show all positions"}</button> : null}<button type="button" className={styles.btnSmall} disabled={running || weightState.submittedSum <= 0} onClick={() => {setDirty(true); setComparison(null); setProposed(normalizeWeights(proposed));}}>Normalize to 100%</button><button type="button" className={styles.btnSmall} disabled={running || Boolean(compatibilityProblem) || analystIncomplete || missingTarget} onClick={optimize}>Run optimization</button></div>
      <section><h2 className={styles.h2}>Portfolio metrics (historical model)</h2><table className={styles.metrics}><thead><tr><th>Metric</th><th>Current</th><th>Proposed</th></tr></thead><tbody>{metricRows.map(row => <tr key={row.key}><td>{row.head}<small>{row.sub}</small></td><td>{comparison || row.key === "max_drawdown" ? row.cur : "—"}</td><td>{comparison ? row.pro : "—"}</td></tr>)}</tbody></table></section>
      {extrasError ? <p className={styles.sub}>Sector mix and drawdown request failed: {extrasError}</p> : null}
      {extras?.max_drawdown ? <p className={styles.sub}>Drawdown: {extras.max_drawdown.note ?? `${extras.max_drawdown.basis}${extras.max_drawdown.sample ? ` (${formatDate(extras.max_drawdown.sample.start)} to ${formatDate(extras.max_drawdown.sample.end)}, ${extras.max_drawdown.sample.observations} observations)` : ""}.`}</p> : null}
      {comparison ? <details id="build-checks" className={styles.details}><summary>View failed and unavailable checks</summary>{comparison.proposed_compliance.checks.map((check,index) => <div key={index}>{String(check.name ?? check.rule ?? check.constraint ?? "IPS check")} · {humanize(String(check.status ?? "not_evaluated"))}{typeof check.reason === "string" ? ` · ${check.reason}` : ""}</div>)}<ComparisonTable metrics={comparison.metrics}/></details> : null}
      {diagnostics ? <details className={styles.details}><summary>Optimizer diagnostics</summary><pre>{JSON.stringify(diagnostics,null,2)}</pre></details> : null}
    </main>
    <aside data-portfolio-panel="context" className={styles.rail}>
      <h2 className={styles.h2}>Proposal review</h2><p className={`${styles.notice} ${comparison?.proposed_compliance.status === "BREACH" ? styles.noticeBad : ""}`}>{proposalStatus}</p>
      {insights ? <div className={styles.insight}>{insights.lines.map(line => <p key={line}>{line}</p>)}</div> : <p className={styles.sub}>Compare the allocation to evaluate modeled changes and IPS checks.</p>}
      <section className={styles.insight}><h3>Stored constraints</h3>{confirmed ? <dl className={styles.constraints}>{mandate.map(([label,value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : <p className={styles.sub}>—</p>}<Link className={styles.link} href={`/portfolios/${portfolioId}/ips` as never}>Review IPS →</Link>{comparison ? <a className={styles.checkLink} href="#build-checks" onClick={() => {const details = document.getElementById("build-checks") as HTMLDetailsElement | null; if(details) details.open=true;}}>View failed checks</a> : null}</section>
      <section className={styles.insight}><h3>Methodology</h3><p>{comparison ? humanize(String(comparison.assumptions?.expected_return_method ?? "Unavailable")) : "—"}</p><p>{comparison ? "Comparison includes cash; historical model output, not a forecast." : savedAllocation ? `Stored ${humanize(savedAllocation.kind).toLowerCase()} allocation v${savedAllocation.version}.` : "No saved proposal."}</p>{comparison?.warnings?.map(line => <p key={line}>{line}</p>)}<Link className={styles.link} href={`/portfolios/${portfolioId}/quant` as never}>Open quant analysis →</Link></section>
      <section className={styles.ask}><h3>Ask</h3><form onSubmit={event => {event.preventDefault(); if(question.trim()) assistant?.open(question.trim());}}><textarea aria-label="Ask about this proposal" placeholder="Explain the allocation changes" value={question} onChange={event => setQuestion(event.target.value)}/><button type="submit" aria-label="Open assistant with proposal question" disabled={!question.trim()}>↑</button></form></section>
    </aside>
  </div>;
}
