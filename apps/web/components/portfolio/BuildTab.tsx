"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ComparisonTable } from "@/components/DecisionTables";
import { CompanyLogo } from "@/components/markets/CompanyLogo";
import styles from "@/components/portfolio/build/build.module.css";
import type { WorkspaceData } from "@/components/workspace/useWorkspaceData";
import { PortfolioComparison, comparePortfolio, createAllocation, decideRecommendation, runOptimizer } from "@/lib/api";
import { BuildExtras, getBuildExtras } from "@/lib/api/portfolio-build";
import { normalizeWeights, weightSummary } from "@/lib/analytics";
import { formatDate, formatNumber, humanize, numeric } from "@/lib/overview";
import { buildInsights, buildRows, ipsFit, labelFor, metricOf, objectiveOptions, objectivesNeedingReturns, returnMethodOptions, sectorSegments } from "@/lib/portfolio-build";

const SECTOR_COLORS = ["#176044", "#4a86c5", "#d9a441", "#7a5aa6", "#b44d41"];
const OTHERS_COLOR = "#c3c8c0";
const DEFAULT_OBJECTIVE = "target_return_minimum_variance";
const DEFAULT_METHOD = "historical_shrunk";

const pctOf = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toFixed(digits)}%`;
const signedPp = (value: number | null | undefined, digits = 1) => value == null || !Number.isFinite(value) ? "" : `${value > 0 ? "+" : value < 0 ? "-" : ""}${Math.abs(value * 100).toFixed(digits)}%`;
const tone = (value: number | null | undefined, goodWhenPositive = true) => value == null || Math.abs(value) < 1e-9 ? "" : (value > 0) === goodWhenPositive ? styles.pos : styles.neg;
const constraintPct = (value: unknown) => { const n = numeric(value); return n == null ? "Not set" : pctOf(n, 1); };

export function BuildTab({ portfolioId, data, setMessage }: { portfolioId: string; data: WorkspaceData; setMessage: (message: string) => void }) {
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
  const [targetVolatility, setTargetVolatility] = useState("15");
  const [targetBeta, setTargetBeta] = useState("1");
  const [running, setRunning] = useState(false);
  const [comparison, setComparison] = useState<PortfolioComparison | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [extras, setExtras] = useState<BuildExtras | null>(null);
  const [extrasError, setExtrasError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [view, setView] = useState<"allocation" | "metrics">("allocation");
  useEffect(() => setProposed(current), [current]);

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
      setProposed(result.weights);
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
  function reset() { setObjective(DEFAULT_OBJECTIVE); setMethod(DEFAULT_METHOD); setTargetVolatility("15"); setTargetBeta("1"); setAnalystReturns({}); setProposed(current); setComparison(null); setDiagnostics(null); }
  const setWeight = (symbol: string, percent: string) => setProposed(values => ({ ...values, [symbol]: Math.max(0, Number(percent) || 0) / 100 }));

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
      <td className={styles.name} title={nameOf(row.symbol)}>{nameOf(row.symbol)}</td>
      {side === "current" ? <>
        <td className={styles.num}>{pctOf(value)}</td>
        <td className={styles.barCell}><div className={styles.bar}><span style={{ width: `${Math.min(100, value * 100)}%` }} /></div></td>
      </> : <>
        <td className={styles.num}><input className={styles.weightInput} aria-label={`${row.symbol} proposed percent`} type="number" min="0" max="100" step="0.1" value={Number((value * 100).toFixed(2))} onChange={event => setWeight(row.symbol, event.target.value)} /></td>
        <td className={`${styles.barCell}`}><div className={`${styles.bar} ${styles.barProposed}`}><span style={{ width: `${Math.min(100, value * 100)}%` }} /></div></td>
        <td className={`${styles.num} ${tone(row.delta)}`}>{Math.abs(row.delta) < 0.00005 ? "0.0%" : signedPp(row.delta)}</td>
      </>}
    </tr>;
  };
  const othersRow = (side: "current" | "proposed") => rowsView.others ? <tr key={`o-${side}`}>
    <td /><td><strong>Others</strong></td><td className={styles.name}>{rowsView.others.count} holdings</td>
    <td className={styles.num}>{pctOf(side === "current" ? rowsView.others.current : rowsView.others.proposed)}</td>
    <td className={styles.barCell}><div className={`${styles.bar} ${side === "proposed" ? styles.barProposed : ""}`}><span style={{ width: `${Math.min(100, (side === "current" ? rowsView.others.current : rowsView.others.proposed) * 100)}%` }} /></div></td>
    {side === "proposed" ? <td className={`${styles.num} ${tone(rowsView.others.delta)}`}>{signedPp(rowsView.others.delta)}</td> : null}
  </tr> : null;

  const allocationBar = (title: string, weights: Record<string, number> | null | undefined) => {
    const segments = sectorSegments(weights);
    return <div>
      <h3 className={styles.h3}>{title}</h3>
      {segments.length ? <>
        <div className={styles.stack}>{segments.map((segment, index) => <span key={segment.label} title={`${segment.label} ${pctOf(segment.value)}`} style={{ width: `${segment.value * 100}%`, background: segment.label === "Others" ? OTHERS_COLOR : SECTOR_COLORS[index % SECTOR_COLORS.length] }} />)}</div>
        <div className={styles.legend}>{segments.map((segment, index) => <span key={segment.label}><i className={styles.dot} style={{ background: segment.label === "Others" ? OTHERS_COLOR : SECTOR_COLORS[index % SECTOR_COLORS.length] }} />{segment.label} {pctOf(segment.value)}</span>)}</div>
      </> : <p className={styles.empty}>Sector mix unavailable.</p>}
    </div>;
  };

  return <div className={styles.root}>
    <div className={styles.notice}><strong>Decision support only.</strong> Optimizer and sandbox actions create immutable proposals; they never execute trades or mutate the transaction ledger.{recommendationId ? " Saving here will link the proposal to the recommendation under review." : ""}</div>
    {summary.valuation_complete === false ? <div className={`${styles.notice} ${styles.noticeBad}`}><strong>Portfolio valuation is incomplete.</strong> {summary.valuation_note ?? `Missing prices: ${summary.unpriced_symbols.join(", ")}`}</div> : null}
    {!data.assumptions ? <div className={styles.notice}><strong>Assumptions unavailable.</strong> Aligned price history is required before portfolio construction can be audited.</div> : null}

    <div className={styles.board}>
      <section className={styles.col}>
        <h2 className={styles.h2}>Current portfolio</h2>
        <p className={styles.sub}>Based on {summary.data_freshness_date ? `holdings valued ${formatDate(summary.data_freshness_date)}` : "latest holdings"} · Total value PKR {formatNumber(summary.total_value, 0)}</p>
        <table className={styles.table}><thead><tr><th>#</th><th>Symbol</th><th>Name</th><th className={styles.num}>Weight</th><th /></tr></thead>
          <tbody>{rowsView.rows.map((row, index) => renderRow(row, index, "current"))}{othersRow("current")}</tbody></table>
        {Object.keys(buildRows(current, proposed, null).rows).length > 10 ? <div className={styles.btnRow}><button type="button" className={styles.btnSmall} onClick={() => setShowAll(value => !value)}>{showAll ? "Show top 10" : "Show all positions"}</button></div> : null}
      </section>

      <section className={styles.col}>
        <label className={styles.label} htmlFor="build-objective">Optimization objective</label>
        <select id="build-objective" className={styles.field} value={objective} onChange={event => setObjective(event.target.value)}>{objectiveOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
        <label className={styles.label} htmlFor="build-method">Expected return method</label>
        <select id="build-method" className={styles.field} value={method} disabled={!usesReturns} onChange={event => setMethod(event.target.value)}>{returnMethodOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
        {objective === "target_volatility_maximum_return" ? <><label className={styles.label} htmlFor="build-vol">Target volatility, %</label><input id="build-vol" className={styles.field} type="number" min="0.1" step="0.1" value={targetVolatility} onChange={event => setTargetVolatility(event.target.value)} /></> : null}
        {objective === "target_beta" ? <><label className={styles.label} htmlFor="build-beta">Target beta</label><input id="build-beta" className={styles.field} type="number" step="0.05" value={targetBeta} onChange={event => setTargetBeta(event.target.value)} /></> : null}
        {usesReturns && method === "user_model" ? <div><p className={styles.sub}>Explicit annual nominal returns (%), stored with the run and not presented as observed facts.</p><div className={styles.analyst}>{riskySymbols.map(symbol => <label key={symbol}>{symbol}<input type="number" step="0.1" value={analystReturns[symbol] ?? ""} onChange={event => setAnalystReturns(values => ({ ...values, [symbol]: event.target.value }))} /></label>)}</div></div> : null}

        <div className={styles.mandate}>
          <div className={styles.mandateHead}><h3 className={styles.h3}>Mandate &amp; constraints</h3><Link href={`/portfolios/${portfolioId}/ips` as never}>Edit</Link></div>
          {confirmed ? <dl>{mandate.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl> : <p className={styles.empty}>No confirmed IPS. Confirm one on the IPS tab.</p>}
        </div>
        {compatibilityProblem ? <div className={`${styles.notice} ${styles.noticeBad}`} style={{ marginBottom: 12 }}>{compatibilityProblem}</div> : null}
        <button type="button" className={styles.btn} disabled={running || Boolean(compatibilityProblem) || analystIncomplete} onClick={optimize}>{running ? "Calculating…" : "Run optimization"}</button>
        <button type="button" className={`${styles.btn} ${styles.btnGhost}`} disabled={running} onClick={reset}>Reset to defaults</button>
      </section>

      <section className={styles.col}>
        <h2 className={styles.h2}>Proposed portfolio</h2>
        <p className={styles.sub}>{comparison ? `${comparison.label} · data as of ${formatDate(comparison.data_cutoff)}` : "No proposal yet. Run the optimizer or edit weights directly."}</p>
        <table className={styles.table}><thead><tr><th>#</th><th>Symbol</th><th>Name</th><th className={styles.num}>Weight</th><th /><th className={styles.num}>Δ</th></tr></thead>
          <tbody>{rowsView.rows.map((row, index) => renderRow(row, index, "proposed"))}{othersRow("proposed")}</tbody></table>
        <div className={styles.btnRow}>
          <span className={`${styles.mono} ${weightState.valid ? styles.muted : styles.neg}`} style={{ alignSelf: "center", fontSize: 12.5 }}>{pctOf(weightState.submittedSum, 2)} allocated</span>
          <button type="button" className={styles.btnSmall} disabled={running || weightState.submittedSum <= 0} onClick={() => setProposed(normalizeWeights(proposed))}>Normalize to 100%</button>
          <button type="button" className={styles.btnSmall} disabled={running || !weightState.valid} onClick={() => void analyze()}>Compare impact</button>
          <button type="button" className={styles.btnSmall} disabled={running || !weightState.valid} onClick={saveSandbox}>Save sandbox</button>
        </div>
      </section>

      <aside className={`${styles.col} ${styles.rail}`}>
        <h2 className={styles.h2} style={{ fontSize: 20, marginBottom: 14 }}>Optimization insights</h2>
        {insights ? <>
          <div className={styles.insight}><h3 className={styles.h3}>Modeled change</h3>{insights.lines.map(line => <p key={line}>{line}</p>)}</div>
          <div className={styles.insight}><h3 className={styles.h3}>IPS check</h3><p>{insights.compliance}{insights.notEvaluated ? ` ${insights.notEvaluated} check(s) could not be evaluated.` : ""}</p></div>
          <div className={styles.insight}><h3 className={styles.h3}>Key changes</h3>{insights.changes.length ? <ul>{insights.changes.map(line => <li key={line}>{line}</li>)}</ul> : <p>No weight moved by 0.05 pp or more.</p>}</div>
          {comparison?.warnings?.length ? <div className={styles.insight}><h3 className={styles.h3}>Warnings</h3><ul>{comparison.warnings.map(line => <li key={line}>{line}</li>)}</ul></div> : null}
        </> : <div className={styles.insight}>Insights appear after a proposal is compared; they are derived only from the computed metrics.</div>}
        <div className={styles.insight}>
          <h3 className={styles.h3}>Methodology</h3>
          <p>{labelFor(objectiveOptions, objective)}{usesReturns ? ` using ${labelFor(returnMethodOptions, method).toLowerCase()} expected returns` : " (no expected-return input)"}, with covariance from aligned daily price history and IPS constraints as stored.{typeof diagnostics?.reason === "string" ? ` ${diagnostics.reason}` : ""}</p>
          <Link className={styles.link} href={`/portfolios/${portfolioId}/quant` as never}>Open quant analysis →</Link>
        </div>
      </aside>
    </div>

    <section>
      <div className={styles.compareHead}>
        <h2 className={styles.h2}>Portfolio comparison</h2>
        <div className={styles.toggle}><button type="button" aria-pressed={view === "allocation"} onClick={() => setView("allocation")}>Allocation view</button><button type="button" aria-pressed={view === "metrics"} onClick={() => setView("metrics")}>Metrics view</button></div>
      </div>
      {extrasError ? <div className={styles.notice} style={{ marginBottom: 14 }}>Proposed sector mix and drawdown are unavailable ({extrasError}).</div> : null}
      {view === "allocation" ? <div className={styles.allocs}>
        {allocationBar("Current portfolio allocation", extras?.sector_weights.current ?? holdingSectorWeights)}
        {comparison ? allocationBar("Proposed portfolio allocation", extras?.sector_weights.proposed) : <div><h3 className={styles.h3}>Proposed portfolio allocation</h3><p className={styles.empty}>Compare a proposal to see its sector mix.</p></div>}
      </div> : null}
      {view === "metrics" || comparison ? <table className={styles.metrics} style={{ marginTop: view === "allocation" ? 28 : 0 }}>
        <thead><tr><th />{metricRows.map(row => <th key={row.key}>{row.head}<small style={{ display: "block", fontSize: 11 }}>{row.sub}</small></th>)}</tr></thead>
        <tbody>
          <tr><td>Current portfolio</td>{metricRows.map(row => <td key={row.key}>{comparison || row.key === "max_drawdown" ? row.cur : "—"}</td>)}</tr>
          <tr><td><strong>Proposed portfolio</strong></td>{metricRows.map(row => <td key={row.key} className={row.deltaTone}>{comparison ? row.pro : "—"}{row.delta ? <small>{row.delta}</small> : null}</td>)}</tr>
        </tbody>
      </table> : null}
      {!comparison ? <p className={styles.empty}>Run the optimizer or use Compare impact to populate the metrics. Nothing here is estimated until it is computed.</p> : null}
      {extras?.max_drawdown ? <p className={styles.sub} style={{ marginTop: 10 }}>Max drawdown: {extras.max_drawdown.note ?? `${extras.max_drawdown.basis}${extras.max_drawdown.sample ? ` (${formatDate(extras.max_drawdown.sample.start)} to ${formatDate(extras.max_drawdown.sample.end)}, ${extras.max_drawdown.sample.observations} daily observations)` : ""}.`}</p> : extrasError ? <p className={styles.sub}>Max drawdown unavailable until the build-extras endpoint responds.</p> : null}
    </section>

    {comparison ? <details className={styles.details}><summary>Full before / after decision record</summary><ComparisonTable metrics={comparison.metrics} /><p className={styles.sub}>Status: {humanize(comparison.proposed_compliance.status ?? "not_evaluated")}</p></details> : null}
    {diagnostics ? <details className={styles.details}><summary>Optimizer diagnostics</summary><pre style={{ overflow: "auto", fontSize: 11 }}>{JSON.stringify(diagnostics, null, 2)}</pre></details> : null}
  </div>;
}
