"use client";

import ReactECharts from "echarts-for-react";
import { formatDate, formatNumber } from "@/lib/overview";
import type { ClosePoint } from "@/lib/markets";

export function IndexChart({ points, name }: { points: ClosePoint[]; name: string }) {
  if (points.length < 2) return <p style={{ color: "#73736b", fontSize: 12 }}>At least two stored closes are needed to draw {name}.</p>;
  const up = points[points.length - 1].close >= points[0].close;
  const color = up ? "#176044" : "#b44d41";
  const values = points.map(point => point.close);
  const min = Math.min(...values), max = Math.max(...values), pad = (max - min) * 0.1 || max * 0.01;
  return <div role="img" aria-label={`${name} closing level from ${formatDate(points[0].date)} to ${formatDate(points[points.length - 1].date)}`}>
    <ReactECharts notMerge style={{ height: 250, width: "100%" }} option={{
      animation: false,
      grid: { left: 4, right: 4, top: 10, bottom: 4, containLabel: true },
      tooltip: { trigger: "axis", valueFormatter: (value: number) => formatNumber(value), backgroundColor: "#faf8f1", borderColor: "#ded8cb", textStyle: { color: "#18251e", fontSize: 12 } },
      xAxis: { type: "category", boundaryGap: false, data: points.map(point => point.date), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { hideOverlap: true, color: "#727269", fontSize: 10, formatter: (value: string) => formatDate(value).slice(0, 6) } },
      yAxis: { type: "value", position: "right", min: Math.floor(min - pad), max: Math.ceil(max + pad), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#727269", fontSize: 10, formatter: (value: number) => formatNumber(value, 0) }, splitLine: { show: false } },
      series: [{ name, type: "line", data: values, showSymbol: false, smooth: false, lineStyle: { color, width: 1.8 },
        areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${color}38` }, { offset: 1, color: `${color}05` }] } } }],
    }} />
  </div>;
}
