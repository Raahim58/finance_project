"use client";

import type { RefObject } from "react";
import ReactECharts from "echarts-for-react";

export type ChartRef = RefObject<ReactECharts | null>;

// Thin wrapper so every sub-tab attaches the same ref and "Export chart" can read the live canvas.
export function QuantChart({ option, height = 400, chartRef }: { option: object; height?: number; chartRef: ChartRef }) {
  return <ReactECharts ref={chartRef} notMerge lazyUpdate style={{ height, width: "100%" }} option={option} />;
}
