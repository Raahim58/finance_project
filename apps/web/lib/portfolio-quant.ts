import type { CapitalMarketAssumptions, CapmSml, EfficientFrontier, PortfolioQuant, ReturnDistribution, RollingRisk } from "@/lib/api";
import { numeric } from "@/lib/overview";

export const quantTabs = [
  { id: "frontier", label: "Efficient frontier" },
  { id: "capm", label: "CAPM / SML" },
  { id: "correlation", label: "Correlation" },
  { id: "rolling", label: "Rolling risk" },
  { id: "distribution", label: "Distribution" },
  { id: "contribution", label: "Risk contribution" },
] as const;
export type QuantTabId = typeof quantTabs[number]["id"];

export type ComparePoint = {
  id: "current" | "global_minimum_variance" | "maximum_sharpe" | "benchmark" | "risk_free";
  label: string;
  tone: "current" | "alternative" | "muted";
  expectedReturn: number | null;
  volatility: number | null;
  plottable: boolean;
  /** Present when the point cannot be drawn; explains which input is missing. */
  reason?: string;
};

// Fractions (decimal API values) rendered as percentages. Missing stays missing.
export function pctFraction(value: unknown, digits = 1, signed = false) {
  const result = numeric(value);
  if (result == null) return "—";
  const text = `${signed && result > 0 ? "+" : ""}${(result * 100).toFixed(digits)}%`;
  return text;
}

export function signedNumber(value: unknown, digits = 2) {
  const result = numeric(value);
  return result == null ? "—" : `${result > 0 ? "+" : ""}${result.toFixed(digits)}`;
}

export function riskFreeRate(assumptions: CapitalMarketAssumptions | null, frontier: EfficientFrontier | null): number | null {
  const fromAssumptions = numeric((assumptions?.risk_free as Record<string, unknown> | null | undefined)?.annual_rate);
  return fromAssumptions ?? numeric((frontier?.assumptions as Record<string, unknown> | undefined)?.risk_free_rate);
}

export function sharpeRatio(expectedReturn: number | null, volatility: number | null, rf: number | null) {
  if (expectedReturn == null || volatility == null || rf == null || volatility <= 0) return null;
  return (expectedReturn - rf) / volatility;
}

export function comparePoints(frontier: EfficientFrontier | null, assumptions: CapitalMarketAssumptions | null, quant: PortfolioQuant | null): ComparePoint[] {
  const markers = (frontier?.markers ?? {}) as Record<string, { expected_return: number; volatility: number } | null | undefined>;
  const marker = (key: string, id: ComparePoint["id"], label: string, tone: ComparePoint["tone"], missing: string): ComparePoint => {
    const point = markers[key];
    const expectedReturn = numeric(point?.expected_return), volatility = numeric(point?.volatility);
    const ok = expectedReturn != null && volatility != null;
    return { id, label, tone, expectedReturn, volatility, plottable: ok, reason: ok ? undefined : missing };
  };
  const rf = riskFreeRate(assumptions, frontier);
  const benchmark = (quant?.benchmark ?? {}) as Record<string, unknown>;
  const benchmarkReturn = numeric(benchmark.market_arithmetic_expected_return);
  const benchmarkLabel = typeof benchmark.symbol === "string" && benchmark.symbol ? `${benchmark.symbol} (benchmark)` : "Benchmark";
  return [
    marker("current", "current", "Current portfolio", "current", "Current allocation could not be modeled."),
    marker("global_minimum_variance", "global_minimum_variance", "Global minimum variance", "alternative", "Not returned by the optimizer."),
    marker("maximum_sharpe", "maximum_sharpe", "Maximum Sharpe", "alternative", "Requires an observed risk-free rate."),
    {
      id: "benchmark", label: benchmarkLabel, tone: "muted", expectedReturn: benchmarkReturn, volatility: null, plottable: false,
      reason: benchmarkReturn == null ? (typeof benchmark.reason === "string" ? benchmark.reason : "Benchmark statistics unavailable.") : "Benchmark volatility is not returned by the model.",
    },
    {
      id: "risk_free", label: "Risk-free rate", tone: "muted", expectedReturn: rf, volatility: rf == null ? null : 0, plottable: rf != null,
      reason: rf == null ? "No observed effective-dated risk-free series." : undefined,
    },
  ];
}

export type Kpi = { expectedReturn: number | null; volatility: number | null; sharpe: number | null; maxDrawdown: number | null; beta: number | null };

// Expected return / volatility are risky-sleeve model values; drawdown and beta are ledger-history values
// that only exist for the current portfolio, so alternatives never borrow them.
export function kpiFor(point: ComparePoint | undefined, rf: number | null, quant: PortfolioQuant | null): Kpi {
  const isCurrent = point?.id === "current";
  const metrics = (quant?.benchmark?.metrics ?? {}) as Record<string, unknown>;
  return {
    expectedReturn: point?.expectedReturn ?? null,
    volatility: point?.volatility ?? null,
    sharpe: sharpeRatio(point?.expectedReturn ?? null, point?.volatility ?? null, rf),
    maxDrawdown: isCurrent ? numeric((quant?.portfolio as Record<string, unknown> | undefined)?.max_drawdown) : null,
    beta: isCurrent ? numeric(metrics.beta) : null,
  };
}

export function delta(value: number | null, base: number | null) {
  return value == null || base == null ? null : value - base;
}

export function toCsv(rows: Array<Array<string | number | null | undefined>>) {
  const cell = (value: string | number | null | undefined) => {
    if (value == null) return "";
    const text = String(value);
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  return rows.map(row => row.map(cell).join(",")).join("\n");
}

type ExportContext = {
  frontier: EfficientFrontier | null; assumptions: CapitalMarketAssumptions | null; capm: CapmSml | null;
  rolling: RollingRisk | null; distribution: ReturnDistribution | null; quant: PortfolioQuant | null;
};

// Rows for the active sub-tab, taken verbatim from API payloads.
export function exportRows(tab: QuantTabId, ctx: ExportContext): Array<Array<string | number | null>> | null {
  if (tab === "frontier") {
    if (!ctx.frontier?.points.length) return null;
    const symbols = Object.keys(ctx.frontier.points[0].weights);
    return [["series", "label", "volatility", "expected_return", ...symbols.map(symbol => `weight_${symbol}`)],
      ...ctx.frontier.points.map(point => ["frontier", "", point.volatility, point.expected_return, ...symbols.map(symbol => point.weights[symbol] ?? null)]),
      ...Object.entries(ctx.frontier.markers ?? {}).filter(([, point]) => point).map(([key, point]) => ["marker", key, point!.volatility, point!.expected_return, ...symbols.map(symbol => point!.weights[symbol] ?? null)]),
      ...(ctx.assumptions?.securities ?? []).map(item => ["asset", item.symbol, item.volatility ?? null, item.expected_return ?? null, ...symbols.map(() => null)])];
  }
  if (tab === "capm") {
    if (!ctx.capm?.available) return null;
    return [["symbol", "beta", "realized_return", "capm_return", "jensen_alpha"], ...(ctx.capm.securities ?? []).map(item => [item.symbol, item.beta, item.realized_return, item.capm_return, item.jensen_alpha])];
  }
  if (tab === "correlation") {
    const symbols = ctx.quant?.symbols ?? [], matrix = ctx.quant?.correlation ?? [];
    return matrix.length ? [["", ...symbols], ...matrix.map((row, index) => [symbols[index], ...row])] : null;
  }
  if (tab === "rolling") {
    const points = ctx.rolling?.points ?? [];
    return points.length ? [["date", "volatility", "sharpe", "drawdown", "beta"], ...points.map(point => [point.date, point.volatility, point.sharpe ?? null, point.drawdown, point.beta ?? null])] : null;
  }
  if (tab === "distribution") {
    const bins = ctx.distribution?.bins ?? [];
    return bins.length ? [["lower", "upper", "count"], ...bins.map(bin => [bin.lower, bin.upper, bin.count])] : null;
  }
  const contributions = Object.entries(ctx.quant?.risk_contributions ?? {});
  return contributions.length ? [["symbol", "risk_contribution"], ...contributions] : null;
}

export function correlationExtremes(matrix: number[][], symbols: string[]) {
  let high: { pair: string; value: number } | null = null;
  for (let row = 0; row < matrix.length; row++) for (let column = 0; column < row; column++) {
    const value = matrix[row][column];
    if (!high || value > high.value) high = { pair: `${symbols[row]} / ${symbols[column]}`, value };
  }
  return high;
}
