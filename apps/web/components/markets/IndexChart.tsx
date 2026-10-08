"use client";

import ReactECharts from "echarts-for-react";
import { useEffect, useRef } from "react";
import { formatDate, formatNumber } from "@/lib/overview";
import type { ClosePoint } from "@/lib/markets";

export function IndexChart({ points, name, liveDate, height = 245, compactAxis = true }: { compactAxis?: boolean; height?: number; points: ClosePoint[]; name: string; liveDate?: string }) {
  const node = useRef<HTMLDivElement>(null), chart = useRef<ReactECharts>(null);
  const available = points.length >= 2;
  useEffect(() => {
    if (!node.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => chart.current?.getEchartsInstance().resize());
    observer.observe(node.current);
    return () => observer.disconnect();
  }, [available]);
  if (!available) return <p style={{ color: "#70757d", fontSize: 12 }}>At least two stored closes are needed to draw {name}.</p>;
  const up = points[points.length - 1].close >= points[0].close;
  const color = up ? "#00875a" : "#d92d20";
  const values = points.map(point => point.close);
  const min = Math.min(...values), max = Math.max(...values), pad = (max - min) * 0.1 || max * 0.01;
  return <div ref={node} role="img" aria-label={`${name} ${liveDate ? "daily closes and latest observed level" : "closing level"} from ${formatDate(points[0].date)} to ${formatDate(points[points.length - 1].date)}`}>
    <ReactECharts ref={chart} notMerge style={{ height, width: "100%" }} option={{
      animation: false,
      grid: { left: 3, right: 5, top: 19, bottom: 9, containLabel: true },
      tooltip: { trigger: "axis", valueFormatter: (value: number) => formatNumber(value), backgroundColor: "#ffffff", borderColor: "#eceef1", textStyle: { color: "#141619", fontSize: 12 }, axisPointer: { type: "line", lineStyle: { color: "#b6bcc4", width: 1 } } },
      xAxis: { type: "category", boundaryGap: false, data: points.map(point => point.date), axisTick: { show: false }, axisLine: { show: false }, axisLabel: { hideOverlap: true, color: "#70757d", fontSize: 11, formatter: (value: string) => formatDate(value).slice(0, 6) } },
      yAxis: { type: "value", position: "right", splitNumber: 3, min: Math.floor(min - pad), max: Math.ceil(max + pad), axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#70757d", fontSize: 11, formatter: (value: number) => compactAxis ? `${(value / 1000).toFixed(1)}K` : formatNumber(value, 0) }, splitLine: { show: true, lineStyle: { color: "#f0f2f4", width: 1 } } },
      series: [{ name, type: "line", data: values, showSymbol: false, smooth: false, lineStyle: { color, width: 1.8 },
        markPoint: { symbol: "circle", symbolSize: 6, label: { show: false }, data: [{ coord: [points.at(-1)!.date, values.at(-1)] }], itemStyle: { color, borderColor: "#fff", borderWidth: 1 } },
        areaStyle: { color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: `${color}1b` }, { offset: 1, color: `${color}00` }] } } }],
    }} />
  </div>;
}
