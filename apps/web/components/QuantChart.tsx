"use client";

import ReactECharts from "echarts-for-react";

export function QuantChart({ labels, values, title }: { labels: string[]; values: number[]; title: string }) {
  return <div className="rounded-lg border border-line bg-white p-4"><ReactECharts style={{ height: 320 }} option={{ title: { text: title, textStyle: { fontSize: 14 } }, tooltip: { trigger: "axis" }, xAxis: { type: "category", data: labels }, yAxis: { type: "value" }, series: [{ type: "bar", data: values, itemStyle: { color: "#157f73" } }] }} /></div>;
}
