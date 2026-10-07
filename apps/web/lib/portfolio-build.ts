import type { ComparisonMetric, PortfolioComparison } from "@/lib/api";
import { numeric } from "@/lib/overview";

// Only objectives and return methods the backend optimizer supports (apps/api/app/domain/quant/optimizer.py).
export const objectiveOptions = [
  { value: "minimum_variance", label: "Minimum variance" },
  { value: "target_return_minimum_variance", label: "Required-return minimum variance" },
  { value: "target_volatility_maximum_return", label: "Target-volatility maximum return" },
  { value: "target_beta", label: "Target beta" },
  { value: "max_sharpe", label: "Maximum Sharpe ratio" },
  { value: "risk_parity", label: "Equal risk contribution" },
  { value: "risk_budget", label: "Custom IPS risk budget" },
] as const;
export const returnMethodOptions = [
  { value: "historical_shrunk", label: "Historical, shrunk" },
  { value: "capm", label: "CAPM" },
  { value: "user_model", label: "Analyst assumptions" },
] as const;
export const objectivesNeedingReturns = ["target_return_minimum_variance", "target_volatility_maximum_return", "target_beta", "max_sharpe"];

export const labelFor = (options: ReadonlyArray<{ value: string; label: string }>, value: string) => options.find(option => option.value === value)?.label ?? value;

export type BuildRow = { symbol: string; current: number; proposed: number; delta: number };
export type BuildRows = { rows: BuildRow[]; others: { count: number; current: number; proposed: number; delta: number } | null };

// Rank by current weight, then proposed-only names by proposed weight. Remainder rolls into "Others".
export function buildRows(current: Record<string, number>, proposed: Record<string, number>, limit: number | null = 10): BuildRows {
  const symbols = [...new Set([...Object.keys(current), ...Object.keys(proposed)])];
  const all = symbols.map(symbol => {
    const c = current[symbol] ?? 0, p = proposed[symbol] ?? 0;
    return { symbol, current: c, proposed: p, delta: p - c };
  }).filter(row => row.current > 0 || row.proposed > 0)
    .sort((a, b) => b.current - a.current || b.proposed - a.proposed || a.symbol.localeCompare(b.symbol));
  if (limit == null || all.length <= limit) return { rows: all, others: null };
  const rest = all.slice(limit);
  const c = rest.reduce((sum, row) => sum + row.current, 0), p = rest.reduce((sum, row) => sum + row.proposed, 0);
  return { rows: all.slice(0, limit), others: { count: rest.length, current: c, proposed: p, delta: p - c } };
}

export function sectorSegments(weights: Record<string, number> | null | undefined, limit = 4) {
  const entries = Object.entries(weights ?? {}).filter(([, value]) => value > 0).sort((a, b) => b[1] - a[1]);
  const head = entries.slice(0, limit).map(([label, value]) => ({ label, value }));
  const rest = entries.slice(limit).reduce((sum, [, value]) => sum + value, 0);
  return rest > 0 ? [...head, { label: "Others", value: rest }] : head;
}

export function metricOf(comparison: PortfolioComparison | null, key: string): ComparisonMetric | null {
  return comparison?.metrics.find(metric => metric.key === key) ?? null;
}

type Check = { status?: string };
// Share of evaluated IPS checks that pass; unevaluated checks are excluded and reported separately.
export function ipsFit(compliance: { checks?: Array<Record<string, unknown>> } | null | undefined) {
  const checks = (compliance?.checks ?? []) as Check[];
  const passed = checks.filter(check => check.status === "PASS").length;
  const breached = checks.filter(check => check.status === "BREACH").length;
  const notEvaluated = checks.filter(check => check.status === "NOT_EVALUATED").length;
  const evaluated = passed + breached;
  return { passed, evaluated, notEvaluated, ratio: evaluated ? passed / evaluated : null };
}

const signedPp = (value: number) => `${value > 0 ? "+" : value < 0 ? "-" : ""}${Math.abs(value * 100).toFixed(2)} pp`;
const pct1 = (value: number) => `${(value * 100).toFixed(1)}%`;

// Insight text is a template over computed numbers only.
export function buildInsights(comparison: PortfolioComparison | null, rows: BuildRow[], fitProposed: ReturnType<typeof ipsFit> | null) {
  if (!comparison) return null;
  const metric = (key: string) => metricOf(comparison, key);
  const lines: string[] = [];
  const parts: Array<[string, ComparisonMetric | null, "decimal" | "ratio"]> = [["Expected return", metric("expected_return"), "decimal"], ["Volatility", metric("volatility"), "decimal"], ["Sharpe ratio", metric("sharpe"), "ratio"]];
  for (const [label, m, unit] of parts) {
    const c = numeric(m?.current), p = numeric(m?.proposed);
    if (c == null || p == null) { lines.push(`${label}: not computable for both portfolios.`); continue; }
    lines.push(unit === "decimal" ? `${label} ${pct1(c)} to ${pct1(p)} (${signedPp(p - c)}).` : `${label} ${c.toFixed(2)} to ${p.toFixed(2)} (${p - c >= 0 ? "+" : ""}${(p - c).toFixed(2)}).`);
  }
  const moves = rows.filter(row => Math.abs(row.delta) >= 0.0005);
  const up = [...moves].filter(row => row.delta > 0).sort((a, b) => b.delta - a.delta).slice(0, 3);
  const down = [...moves].filter(row => row.delta < 0).sort((a, b) => a.delta - b.delta).slice(0, 3);
  const changes = [...up, ...down].map(row => `${row.delta > 0 ? "Increase" : "Reduce"} ${row.symbol} ${pct1(row.current)} to ${pct1(row.proposed)} (${signedPp(row.delta)})`);
  const status = comparison.proposed_compliance.status;
  const compliance = status === "PASS" ? `Proposal passes all ${fitProposed?.evaluated ?? 0} evaluated IPS checks.`
    : status === "BREACH" ? `Proposal breaches ${(fitProposed?.evaluated ?? 0) - (fitProposed?.passed ?? 0)} of ${fitProposed?.evaluated ?? 0} evaluated IPS checks.`
    : "IPS compliance could not be fully evaluated for the proposal.";
  return { lines, changes, compliance, notEvaluated: fitProposed?.notEvaluated ?? 0 };
}
