import { describe, expect, it } from "vitest";
import type { SeriesOption, XAXisComponentOption, YAXisComponentOption } from "echarts";
import { chartOptions } from "./chart-options";
import { technicalTooltip } from "./TechnicalTooltip";
import { defaultSettings, type TechnicalBar } from "@/lib/technical/types";
import { technicalSeries } from "@/lib/technical/series";
const bars: TechnicalBar[] = Array.from({ length: 40 }, (_, i) => ({ date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10), open: i + 10, close: i + 11, low: i + 9, high: i + 12, volume: i * 100, source: "test", changePercent: 1 }));
const indicators = technicalSeries(bars);
describe("chart alignment", () => {
    it.each([true, false])("links every pane and zoom axis with volume=%s", volume => {
        const option = chartOptions(bars, { ...defaultSettings, volume, lower: "macd", overlays: ["ma20", "bollinger"] }, { start: 20, end: 80 }, indicators);
        const x = option.xAxis as Array<XAXisComponentOption & {
            data?: unknown;
        }>, series = option.series as Array<SeriesOption & {
            xAxisIndex?: number;
            yAxisIndex?: number;
        }>;
        expect(x).toHaveLength(volume ? 3 : 2);
        x.forEach(axis => expect(axis.data).toEqual(bars.map(bar => bar.date)));
        expect(series.find(s => s.name === "MACD")?.xAxisIndex).toBe(volume ? 2 : 1);
        expect(series.find(s => s.name === "MACD histogram")?.yAxisIndex).toBe(volume ? 2 : 1);
        const zoom = option.dataZoom as Array<{
            start: number;
            end: number;
            xAxisIndex: number[];
        }>;
        zoom.forEach(z => { expect(z.xAxisIndex).toEqual(x.map((_, i) => i)); expect(z.start).toBe(20); expect(z.end).toBe(80); });
        expect((option.axisPointer as {
            link: unknown;
        }).link).toEqual([{ xAxisIndex: "all" }]);
    });
    it("line mode changes only price and preserves zoom and indicators", () => {
        const option = chartOptions(bars, { ...defaultSettings, mode: "line", overlays: ["ma20"], lower: "rsi" }, { start: 12, end: 60 }, indicators);
        const series = option.series as Array<SeriesOption & {
            xAxisIndex?: number;
            yAxisIndex?: number;
        }>;
        expect(series[0].type).toBe("line");
        expect(series[0].data).toEqual(bars.map(bar => bar.close));
        expect(series.find(s => s.name === "MA20")?.data).toEqual(indicators.ma20);
        const axis = option.yAxis as YAXisComponentOption[];
        expect(axis[2].min).toBe(0);
        expect(axis[2].max).toBe(100);
    });
    it("maps event markers to financial coordinates and their own panes", () => {
        const signal = { id: "event", date: bars[20].date, value: 12, type: "macd_bullish_cross" as const, label: "Crossover", description: "MACD crossed its signal.", pane: "macd" as const };
        const option = chartOptions(bars, { ...defaultSettings, lower: "macd", signals: true }, { start: 0, end: 100 }, indicators, [signal]);
        const marker = (option.series as Array<SeriesOption & {
            xAxisIndex?: number;
            yAxisIndex?: number;
        }>).find(s => s.id === "events-macd")!;
        expect(marker.xAxisIndex).toBe(2);
        expect(marker.yAxisIndex).toBe(2);
        expect((marker.data as Array<{
            value: unknown;
        }>)[0].value).toEqual([signal.date, 12]);
        const hidden = chartOptions(bars, defaultSettings, { start: 0, end: 100 }, indicators, [signal]);
        expect((hidden.series as Array<SeriesOption & {
            xAxisIndex?: number;
            yAxisIndex?: number;
        }>).some(s => s.type === "scatter")).toBe(false);
    });
    it("escapes dynamic tooltip content and exposes OHLCV and unavailable values", () => {
        const tip = technicalTooltip(bars[0], [["<script>", null]], ["<img onerror='x'>"]);
        for (const label of ["Open", "High", "Low", "Close", "Change", "Volume"])
            expect(tip).toContain(label);
        expect(tip).toContain("&lt;script&gt;");
        expect(tip).not.toContain("<img");
        expect(tip).toContain("—");
    });
});
