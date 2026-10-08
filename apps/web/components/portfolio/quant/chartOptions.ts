import type { CapitalMarketAssumptions, CapmSml, EfficientFrontier, ReturnDistribution, RollingRisk } from "@/lib/api";
import type { ComparePoint } from "@/lib/portfolio-quant";

export const palette = { ink: "#16181b", green: "#00a785", red: "#df303e", amber: "#b8872d", slate: "#506c89", line: "#e6e9ee", muted: "#757c89", asset: "#c5cad3", surface: "#ffffff" };
export const markerColor: Record<ComparePoint["id"], string> = {
  current: "#087aff", global_minimum_variance: palette.ink, maximum_sharpe: palette.green, benchmark: palette.slate, risk_free: palette.muted,
};

const font = "Inter, ui-sans-serif, system-ui";
const axis = {
  axisLine: { lineStyle: { color: palette.line } }, axisTick: { show: false },
  axisLabel: { color: palette.muted, fontSize: 11, fontFamily: font },
  splitLine: { lineStyle: { color: "#eef0f4" } },
};
const base = {
  animation: false, aria: { enabled: true }, textStyle: { fontFamily: font, color: palette.ink },
  tooltip: { backgroundColor: palette.surface, borderColor: palette.line, borderWidth: 1, padding: [9, 11], textStyle: { color: palette.ink, fontSize: 12 }, extraCssText: "box-shadow:0 8px 24px #1b211b1a;border-radius:6px" },
};
const pct = (value: number, digits = 1) => `${(value * 100).toFixed(digits)}%`;
const axisName = (name: string, gap: number) => ({ name, nameLocation: "middle" as const, nameGap: gap, nameTextStyle: { color: palette.muted, fontSize: 11 } });

type Datum = { name: string; value: [number, number] };

export function frontierOption(frontier: EfficientFrontier, assumptions: CapitalMarketAssumptions | null, markers: ComparePoint[], showAssets: boolean) {
  const curve = [...frontier.points].sort((a, b) => a.volatility - b.volatility).map(point => [point.volatility, point.expected_return]);
  const assets: Datum[] = showAssets ? (assumptions?.securities ?? []).filter(item => item.volatility != null && item.expected_return != null).map(item => ({ name: item.symbol, value: [item.volatility as number, item.expected_return as number] })) : [];
  const tip = (p: { seriesName: string; data: { name?: string; value: number[] } }) =>
    `<b>${p.data.name || p.seriesName}</b><br/>${pct(p.data.value[1])} expected return<br/>${pct(p.data.value[0])} volatility`;
  return {
    ...base, grid: { left: 8, right: 24, top: 20, bottom: 30, containLabel: true },
    tooltip: { ...base.tooltip, trigger: "item", formatter: tip },
    xAxis: { ...axis, type: "value", scale: true, ...axisName("Volatility (annualized)", 30), axisLabel: { ...axis.axisLabel, formatter: (v: number) => pct(v, 1) } },
    yAxis: { ...axis, type: "value", scale: true, ...axisName("Expected return (annualized)", 48), axisLabel: { ...axis.axisLabel, formatter: (v: number) => pct(v, 0) } },
    series: [
      { name: "Efficient frontier", type: "line", data: curve, showSymbol: true, symbolSize: 5, smooth: false, lineStyle: { color: palette.green, width: 2 }, itemStyle: { color: palette.green }, z: 2 },
      ...(assets.length ? [{ name: "Individual assets", type: "scatter", data: assets, symbolSize: 6, itemStyle: { color: palette.asset, opacity: 0.9 }, label: { show: false, formatter: "{b}", position: "right", color: palette.muted, fontSize: 10 }, z: 1 }] : []),
      ...markers.filter(point => point.plottable && point.expectedReturn != null && point.volatility != null).map(point => ({
        name: point.label, type: "scatter", data: [{ name: point.label, value: [point.volatility as number, point.expectedReturn as number] }],
        symbolSize: point.id === "risk_free" ? 10 : 16, itemStyle: { color: markerColor[point.id], borderColor: "#fff", borderWidth: 2 }, z: 5,
      })),
    ],
  };
}

export function capmOption(capm: CapmSml) {
  const line = [...(capm.sml ?? [])].sort((a, b) => a.beta - b.beta).map(point => [point.beta, point.expected_return]);
  const securities: Datum[] = (capm.securities ?? []).map(item => ({ name: item.symbol, value: [item.beta, item.realized_return] }));
  return {
    ...base, grid: { left: 8, right: 24, top: 20, bottom: 30, containLabel: true },
    tooltip: { ...base.tooltip, trigger: "item", formatter: (p: { seriesName: string; data: { name?: string; value: number[] } }) => `<b>${p.data.name || p.seriesName}</b><br/>Beta ${p.data.value[0].toFixed(2)}<br/>${pct(p.data.value[1])} annual return` },
    xAxis: { ...axis, type: "value", ...axisName("Beta", 30), axisLabel: { ...axis.axisLabel, formatter: (v: number) => v.toFixed(1) } },
    yAxis: { ...axis, type: "value", ...axisName("Annual return", 48), axisLabel: { ...axis.axisLabel, formatter: (v: number) => pct(v, 0) } },
    series: [
      { name: "Security market line", type: "line", data: line, showSymbol: false, lineStyle: { color: palette.green, width: 2 }, z: 2 },
      { name: "Securities (realized)", type: "scatter", data: securities, symbolSize: 11, itemStyle: { color: palette.ink, borderColor: "#fff", borderWidth: 1.5 }, label: { show: true, formatter: "{b}", position: "right", color: palette.muted, fontSize: 10 }, z: 3 },
    ],
  };
}

type LineSeries = { name: string; color: string; values: Array<number | null> };
export function lineOption(labels: string[], series: LineSeries[], format: (v: number) => string) {
  return {
    ...base, legend: { bottom: 0, textStyle: { color: palette.muted, fontSize: 11 }, icon: "circle", itemHeight: 8 },
    grid: { left: 8, right: 20, top: 16, bottom: 44, containLabel: true },
    tooltip: { ...base.tooltip, trigger: "axis", valueFormatter: (v: number | null) => (v == null ? "—" : format(v)) },
    xAxis: { ...axis, type: "category", boundaryGap: false, data: labels, axisLabel: { ...axis.axisLabel, hideOverlap: true } },
    yAxis: { ...axis, type: "value", scale: true, axisLabel: { ...axis.axisLabel, formatter: (v: number) => format(v) } },
    series: series.map(item => ({ name: item.name, type: "line", data: item.values, showSymbol: false, connectNulls: false, lineStyle: { width: 2, color: item.color }, itemStyle: { color: item.color } })),
  };
}

export function rollingSeries(rolling: RollingRisk) {
  const points = rolling.points;
  return {
    labels: points.map(point => point.date),
    risk: [
      { name: "Volatility", color: palette.slate, values: points.map(point => point.volatility ?? null) },
      { name: "Drawdown", color: palette.red, values: points.map(point => point.drawdown ?? null) },
    ],
    ratios: [
      { name: "Sharpe ratio", color: palette.green, values: points.map(point => point.sharpe ?? null) },
      ...(points.some(point => point.beta != null) ? [{ name: "Beta", color: palette.amber, values: points.map(point => point.beta ?? null) }] : []),
    ],
  };
}

export function distributionOption(distribution: ReturnDistribution) {
  const bins = distribution.bins;
  return {
    ...base, grid: { left: 8, right: 20, top: 16, bottom: 34, containLabel: true },
    tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, formatter: (p: Array<{ dataIndex: number; value: number }>) => `${pct(bins[p[0].dataIndex].lower, 2)} to ${pct(bins[p[0].dataIndex].upper, 2)}<br/>${p[0].value} observations` },
    xAxis: { ...axis, type: "category", data: bins.map(bin => pct((bin.lower + bin.upper) / 2, 1)), ...axisName("Daily return", 30), axisLabel: { ...axis.axisLabel, hideOverlap: true } },
    yAxis: { ...axis, type: "value", ...axisName("Observations", 40) },
    series: [{ type: "bar", data: bins.map(bin => bin.count), itemStyle: { color: palette.slate, borderRadius: [2, 2, 0, 0] }, barCategoryGap: "12%" }],
  };
}

export function contributionOption(contributions: Record<string, number>) {
  const rows = Object.entries(contributions).sort((a, b) => a[1] - b[1]);
  return {
    ...base, grid: { left: 8, right: 56, top: 8, bottom: 8, containLabel: true },
    tooltip: { ...base.tooltip, trigger: "axis", axisPointer: { type: "shadow" }, valueFormatter: (v: number) => pct(v, 1) },
    xAxis: { ...axis, type: "value", axisLabel: { ...axis.axisLabel, formatter: (v: number) => pct(v, 0) } },
    yAxis: { ...axis, type: "category", data: rows.map(row => row[0]), splitLine: { show: false } },
    series: [{ type: "bar", data: rows.map(row => row[1]), itemStyle: { color: palette.green, borderRadius: [0, 2, 2, 0] }, label: { show: true, position: "right", formatter: (p: { value: number }) => pct(p.value, 1), color: palette.muted, fontSize: 11 } }],
  };
}

export function correlationOption(symbols: string[], matrix: number[][]) {
  const cells = matrix.flatMap((row, y) => row.map((value, x) => [x, y, Number(value.toFixed(2))]));
  return {
    ...base, grid: { left: 8, right: 8, top: 8, bottom: 56, containLabel: true },
    tooltip: { ...base.tooltip, position: "top", formatter: (p: { value: number[] }) => `${symbols[p.value[1]]} / ${symbols[p.value[0]]}: ${p.value[2].toFixed(2)}` },
    xAxis: { type: "category", data: symbols, splitArea: { show: false }, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: palette.muted, fontSize: 11 } },
    yAxis: { type: "category", data: symbols, inverse: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: palette.muted, fontSize: 11 } },
    visualMap: { min: -1, max: 1, calculable: false, orient: "horizontal", left: "center", bottom: 4, itemWidth: 12, itemHeight: 140, textStyle: { color: palette.muted, fontSize: 11 }, inRange: { color: [palette.red, "#f3efe4", palette.green] } },
    series: [{ type: "heatmap", data: cells, label: { show: symbols.length <= 14, fontSize: 10, color: palette.ink }, itemStyle: { borderColor: palette.surface, borderWidth: 2 } }],
  };
}
