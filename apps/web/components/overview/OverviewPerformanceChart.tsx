"use client";

import ReactECharts from "echarts-for-react";
import type { PortfolioPerformancePoint } from "@/lib/api";
import { formatDate, formatPercent, performanceSeries } from "@/lib/overview";
import styles from "./overview.module.css";

export function OverviewPerformanceChart({ points }: { points: PortfolioPerformancePoint[] }) {
  const series = performanceSeries(points);
  if (series.filter(point => point.value != null).length < 2) return <p className={styles.empty}>At least two dated return observations are needed to display performance.</p>;
  return <div role="img" aria-label={`Cumulative time-weighted portfolio return from ${formatDate(series[0].date)} to ${formatDate(series.at(-1)?.date)}`}>
    <ReactECharts notMerge style={{ height: 185, width: "100%" }} option={{
      animation: false,
      aria: { enabled: true },
      grid: { left: 8, right: 12, top: 14, bottom: 12, containLabel: true },
      tooltip: { trigger: "axis", valueFormatter: (value: number) => formatPercent(value), backgroundColor: "#faf8f1", borderColor: "#ded8cb", textStyle: { color: "#18251e", fontSize: 12 } },
      xAxis: { type: "category", boundaryGap: false, data: series.map(point => point.date), axisTick: { show: false }, axisLine: { lineStyle: { color: "#ded8cb" } }, axisLabel: { hideOverlap: true, color: "#727269", fontSize: 10, formatter: (value: string) => formatDate(value).slice(0, 6) } },
      yAxis: { type: "value", axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#727269", fontSize: 10, formatter: "{value}%" }, splitLine: { lineStyle: { color: "#e9e5db" } } },
      series: [{ name: "Time-weighted return", type: "line", data: series.map(point => point.value), connectNulls: false, showSymbol: true, symbolSize: 4, smooth: false, lineStyle: { color: "#176044", width: 2 }, itemStyle: { color: "#176044" }, areaStyle: { color: "rgba(23,96,68,.07)" } }],
    }} />
  </div>;
}
