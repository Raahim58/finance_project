import type { PortfolioExposure, PortfolioQuant, RollingRisk } from "@/lib/api";
import type { WorkspaceCompliance } from "@/components/workspace/useWorkspaceData";
import { numeric } from "@/lib/overview";

export const riskRanges = ["1M", "3M", "6M", "1Y", "ALL"] as const;
export type RiskRange = typeof riskRanges[number];
const RANGE_DAYS: Record<Exclude<RiskRange, "ALL">, number> = { "1M": 31, "3M": 92, "6M": 183, "1Y": 366 };

export type MetricRow = { label: string; value: string };
export type MandateRow = { rule: string; limit: string; current: string; status: "PASS" | "BREACH" | "NOT_EVALUATED" };
export type RiskIssue = { id: string; title: string; detail: string; level: "High" | "Medium" | "Low"; source: string; when?: string | null };

const record = (value: unknown) => (value ?? {}) as Record<string, unknown>;
export const fraction = (value: unknown, digits = 1, signed = false) => {
  const n = numeric(value);
  return n == null ? "—" : `${signed && n > 0 ? "+" : ""}${(n * 100).toFixed(digits)}%`;
};
export const points = (value: unknown, digits = 1) => {
  const n = numeric(value);
  return n == null ? "—" : `${n.toFixed(digits)}%`;
};
const ratio = (value: unknown, digits = 2) => {
  const n = numeric(value);
  return n == null ? "—" : n.toFixed(digits);
};

export function rollingSeries(rolling: RollingRisk | null, range: RiskRange) {
  const all = (rolling?.points ?? []).map(point => ({ date: point.date, close: point.volatility * 100 }));
  if (range === "ALL" || !all.length) return all;
  const cutoff = Date.parse(all[all.length - 1].date) - RANGE_DAYS[range] * 86_400_000;
  return all.filter(point => Date.parse(point.date) >= cutoff);
}

export function overallRisk(quant: PortfolioQuant | null, totalValue: number | null) {
  const m = record(quant?.portfolio);
  const loss = (key: string) => {
    const f = numeric(m[key]);
    return f == null ? null : { fraction: f, amount: totalValue == null ? null : Math.abs(f) * totalValue };
  };
  return { volatility: numeric(m.annual_volatility), var95: loss("historical_var_95"), es95: loss("historical_es_95"), drawdown: numeric(m.max_drawdown), annualReturn: numeric(m.annual_return) };
}

export function systematicRows(quant: PortfolioQuant | null): { rows: MetricRow[]; unavailable?: string } {
  const b = record(quant?.benchmark?.metrics);
  const unavailable = quant?.benchmark?.available === false ? String(quant.benchmark.reason ?? "Benchmark series unavailable") : undefined;
  return { unavailable, rows: [
    { label: `Beta${quant?.benchmark?.symbol ? ` (vs. ${String(quant.benchmark.symbol)})` : ""}`, value: ratio(b.beta) },
    { label: "Jensen alpha", value: fraction(b.jensen_alpha, 1, true) },
    { label: "Tracking error", value: fraction(b.tracking_error) },
    { label: "Information ratio", value: ratio(b.information_ratio) },
    { label: "Treynor ratio", value: ratio(b.treynor) },
  ] };
}

const topSum = (weights: number[], n: number) => weights.slice().sort((a, b) => b - a).slice(0, n).reduce((a, b) => a + b, 0);

export function concentrationRows(exposure: PortfolioExposure | null, quant: PortfolioQuant | null): MetricRow[] {
  const companies = (exposure?.by_company ?? []).map(row => ({ symbol: row.symbol, w: numeric(row.weight_percent) })).filter((row): row is { symbol: string; w: number } => row.w != null).sort((a, b) => b.w - a.w);
  const sectors = (exposure?.by_sector ?? []).map(row => ({ sector: row.sector, w: numeric(row.weight_percent) })).filter((row): row is { sector: string; w: number } => row.w != null).sort((a, b) => b.w - a.w);
  const ws = companies.map(row => row.w);
  const hhi = numeric(record(quant?.portfolio).concentration_hhi);
  return [
    { label: `Largest holding${companies[0] ? ` (${companies[0].symbol})` : ""}`, value: companies[0] ? points(companies[0].w) : "—" },
    { label: "Top 5 holdings", value: ws.length ? points(topSum(ws, 5)) : "—" },
    { label: "Top 10 holdings", value: ws.length ? points(topSum(ws, 10)) : "—" },
    { label: `Largest sector${sectors[0] ? ` (${sectors[0].sector})` : ""}`, value: sectors[0] ? points(sectors[0].w) : "—" },
    { label: "HHI (holdings)", value: hhi == null ? "—" : hhi.toFixed(3) },
  ];
}

export function tailRows(quant: PortfolioQuant | null): MetricRow[] {
  const m = record(quant?.portfolio);
  return [
    { label: "1-day VaR (95%)", value: fraction(m.historical_var_95) },
    { label: "1-day VaR (99%)", value: fraction(m.historical_var_99) },
    { label: "Expected shortfall (95%)", value: fraction(m.historical_es_95) },
    { label: "Expected shortfall (99%)", value: fraction(m.historical_es_99) },
    { label: "Maximum drawdown", value: fraction(m.max_drawdown) },
  ];
}

export function averagePairwiseCorrelation(matrix: number[][]) {
  let sum = 0, count = 0;
  matrix.forEach((row, i) => row.forEach((value, j) => { if (j > i && Number.isFinite(value)) { sum += value; count += 1; } }));
  return count ? sum / count : null;
}

export function diversificationRows(quant: PortfolioQuant | null): MetricRow[] {
  const hhi = numeric(record(quant?.portfolio).concentration_hhi);
  const contributions = Object.values(quant?.risk_contributions ?? {});
  return [
    { label: "Effective number of holdings", value: hhi ? (1 / hhi).toFixed(1) : "—" },
    { label: "Top 3 holdings risk contribution", value: contributions.length ? fraction(topSum(contributions, 3)) : "—" },
    { label: "Top 5 holdings risk contribution", value: contributions.length ? fraction(topSum(contributions, 5)) : "—" },
    { label: "Average pairwise correlation", value: ratio(averagePairwiseCorrelation(quant?.correlation ?? [])) },
    { label: "Modeled securities", value: String(quant?.symbols.length ?? 0) },
  ];
}

/** Check codes carrying absolute PKR amounts or unitless ratios; everything else is a weight/risk fraction. */
function unitFor(code: string): "pkr" | "ratio" | "fraction" {
  if (code.includes("liquidity")) return "pkr";
  if (code.includes("beta")) return "ratio";
  return "fraction";
}

export function mandateRows(compliance: WorkspaceCompliance | null, exposure: PortfolioExposure | null): MandateRow[] {
  const largestCompany = Math.max(...(exposure?.by_company ?? []).map(row => numeric(row.weight_percent) ?? -Infinity));
  const largestSector = Math.max(...(exposure?.by_sector ?? []).map(row => numeric(row.weight_percent) ?? -Infinity));
  return (compliance?.checks ?? []).filter(check => check.severity !== "not_applicable" || check.status !== "NOT_EVALUATED").map(check => {
    const code = String(check.code ?? ""), limit = numeric(check.limit), actual = numeric(check.actual);
    const current = code === "max_instrument_weight" && Number.isFinite(largestCompany) ? `${largestCompany.toFixed(1)}%`
      : code === "max_sector_weight" && Number.isFinite(largestSector) ? `${largestSector.toFixed(1)}%`
      : "—";
    const bound = code.startsWith("min_") || code.includes("minimum") ? "≥ " : "≤ ";
    const fmt = (value: number | null) => value == null ? "—" : unitFor(code) === "pkr" ? `PKR ${new Intl.NumberFormat("en-PK", { maximumFractionDigits: 0 }).format(value)}` : unitFor(code) === "ratio" ? value.toFixed(2) : fraction(value);
    return { rule: String(check.label ?? code), limit: limit == null ? "—" : `${bound}${fmt(limit)}`, current: current === "—" && actual != null ? fmt(actual) : current, status: (check.status as MandateRow["status"]) ?? "NOT_EVALUATED" };
  });
}

/** Deterministic brief assembled only from the values shown on the page; no generated text. */
export function riskBrief({ breaches, notEvaluated, volatility, topSector }: { breaches: string[]; notEvaluated: number; volatility: number | null; topSector?: string }) {
  const lines: string[] = [];
  lines.push(breaches.length ? `${breaches.length} mandate issue${breaches.length === 1 ? "" : "s"} require attention.` : "No mandate breaches in the evaluated checks.");
  if (volatility != null) lines.push(`Annualized volatility is ${(volatility * 100).toFixed(1)}% on the modeled current allocation.`);
  if (topSector) lines.push(`Largest sector exposure: ${topSector}.`);
  if (notEvaluated) lines.push(`${notEvaluated} check${notEvaluated === 1 ? " is" : "s are"} not evaluated because configuration or data is missing.`);
  return lines;
}
