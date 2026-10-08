import type { EChartsOption, SeriesOption } from "echarts";
import { candleValues } from "@/lib/technical/normalize";
import type { TechnicalBar, ChartSettings } from "@/lib/technical/types";
import type { TechnicalSeries } from "@/lib/technical/series";
import type { PriceLevel } from "@/lib/technical/support-resistance";
import type { TechnicalSignal } from "@/lib/technical/types";
import { visibleSignals } from "@/lib/technical/signals";
import { technicalTooltip, escapeHtml } from "./TechnicalTooltip";
import { chartColors, overlayColors } from "./appearance";
export function chartOptions(bars: TechnicalBar[], settings: ChartSettings, zoom: {
    start: number;
    end: number;
}, indicators?: TechnicalSeries, signals: TechnicalSignal[] = [], levels: PriceLevel[] = []): EChartsOption {
    const c = chartColors, dates = bars.map(bar => bar.date);
    const hasLower = settings.lower !== "none", volumeIndex = settings.volume ? 1 : -1, lowerIndex = hasLower ? (settings.volume ? 2 : 1) : -1;
    const grids = [{ left: 8, right: 65, top: 25, height: hasLower ? "50%" : settings.volume ? "65%" : "82%" }, ...(settings.volume ? [{ left: 8, right: 65, top: hasLower ? "59%" : "75%", height: hasLower ? "10%" : "14%" }] : []), ...(hasLower ? [{ left: 8, right: 65, top: settings.volume ? "76%" : "64%", height: settings.volume ? "14%" : "25%" }] : [])];
    const series: SeriesOption[] = [settings.mode === "candles" ? { id: "price", name: "Price", type: "candlestick", data: candleValues(bars), itemStyle: { color: c.green, color0: c.red, borderColor: c.green, borderColor0: c.red } } : { id: "price", name: "Close", type: "line", data: bars.map(bar => bar.close), showSymbol: false, lineStyle: { color: c.ink, width: 1.5 } }];
    if (settings.volume)
        series.push({ id: "volume", name: "Volume", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: bars.map(bar => ({ value: bar.volume, itemStyle: { color: bar.close >= bar.open ? c.green : c.red, opacity: .55 } })) });
    if (indicators) {
        for (const key of settings.overlays) {
            if (key === "levels")
                continue;
            const lines = key === "bollinger" ? [["BB upper", indicators.bollinger.upper], ["BB middle", indicators.bollinger.middle], ["BB lower", indicators.bollinger.lower]] as const : [[key.toUpperCase(), indicators[key]]] as const;
            for (const [name, data] of lines)
                series.push({ id: name, name, type: "line", data, showSymbol: false, connectNulls: false, lineStyle: { width: 1, color: overlayColors[key], type: key === "bollinger" ? "dashed" : "solid" } });
        }
        if (settings.volume && settings.volumeMA)
            series.push({ id: "volumeMA", name: "Volume MA20", type: "line", data: indicators.volumeMA, xAxisIndex: 1, yAxisIndex: 1, showSymbol: false, lineStyle: { color: c.ochre, width: 1.2 } });
    }
    if (indicators && hasLower) {
        const line = (name: string, data: Array<number | null>, color: string, levels: number[] = []) => {
            series.push({ id: name, name, type: "line", data, xAxisIndex: lowerIndex, yAxisIndex: lowerIndex, showSymbol: false, connectNulls: false, lineStyle: { color, width: 1.2 }, markLine: levels.length ? { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: c.muted, type: "dashed", width: 1 }, data: levels.map(yAxis => ({ yAxis })) } : undefined });
        };
        if (settings.lower === "macd") {
            series.push({ id: "histogram", name: "MACD histogram", type: "bar", data: indicators.macd.histogram.map(value => ({ value, itemStyle: { color: value != null && value >= 0 ? c.green : c.red, opacity: .55 } })), xAxisIndex: lowerIndex, yAxisIndex: lowerIndex });
            line("MACD", indicators.macd.line, c.blue, [0]);
            line("MACD signal", indicators.macd.signal, c.ochre);
        }
        else if (settings.lower === "rsi")
            line("RSI (14)", indicators.rsi, c.blue, [30, 70]);
        else if (settings.lower === "roc")
            line("ROC (12)", indicators.roc, c.blue, [0]);
        else {
            line("Stochastic %K", indicators.stochastic.k, c.blue, [20, 80]);
            line("Stochastic %D", indicators.stochastic.d, c.ochre);
        }
    }
    if (settings.overlays.includes("levels")) {
        for (const level of levels)
            series.push({ id: level.id, name: `Pivot level ${level.value.toFixed(2)}`, type: "line", showSymbol: false, data: [], markLine: { silent: true, symbol: "none", lineStyle: { color: c.muted, type: "dashed", width: 1 }, label: { show: true, formatter: level.value.toFixed(2), color: c.muted, fontSize: 9, position: "insideEndTop" }, data: [{ yAxis: level.value }] } });
    }
    const markers = visibleSignals(signals, settings);
    for (const pane of ["price", "volume", "macd"] as const) {
        const index = pane === "price" ? 0 : pane === "volume" ? volumeIndex : lowerIndex;
        if (index < 0)
            continue;
        const events = markers.filter(signal => signal.pane === pane);
        if (events.length)
            series.push({ id: `events-${pane}`, name: `${pane} events`, type: "scatter", xAxisIndex: index, yAxisIndex: index, symbol: "triangle", symbolSize: 7, z: 8, data: events.map(signal => ({ name: signal.label, value: [signal.date, signal.value], signal, itemStyle: { color: signal.type.includes("bearish") || signal.type.includes("lower") || signal.type.includes("breakdown") ? c.red : c.green } })), tooltip: { trigger: "item", formatter: (params: unknown) => { const signal = (params as {
                        data: {
                            signal: TechnicalSignal;
                        };
                    }).data.signal; return `<div style="max-width:230px;white-space:normal;font-size:11px">${escapeHtml(signal.label)}<br/>${escapeHtml(signal.date)}<br/>${escapeHtml(signal.description)}</div>`; } } });
    }
    return { animation: false, aria: { enabled: true }, textStyle: { fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif' }, grid: grids, axisPointer: { link: [{ xAxisIndex: "all" }] },
        tooltip: { trigger: "axis", confine: true, backgroundColor: "#fff", borderColor: c.line, padding: 8, textStyle: { color: c.ink }, axisPointer: { type: "cross" }, formatter: (params: unknown) => {
                const p = (Array.isArray(params) ? params : [params]) as Array<{
                    dataIndex: number;
                }>;
                const bar = bars[p[0]?.dataIndex];
                const i = p[0]?.dataIndex;
                const values: Array<[
                    string,
                    number | null
                ]> = [];
                if (indicators)
                    for (const key of settings.overlays) {
                        if (key === "levels")
                            continue;
                        if (key === "bollinger")
                            values.push(["BB upper", indicators.bollinger.upper[i]], ["BB middle", indicators.bollinger.middle[i]], ["BB lower", indicators.bollinger.lower[i]]);
                        else
                            values.push([key.toUpperCase(), indicators[key][i]]);
                    }
                if (indicators && settings.volume && settings.volumeMA)
                    values.push(["Volume MA20", indicators.volumeMA[i]]);
                if (indicators && hasLower) {
                    if (settings.lower === "macd")
                        values.push(["MACD", indicators.macd.line[i]], ["Signal", indicators.macd.signal[i]], ["Histogram", indicators.macd.histogram[i]]);
                    else if (settings.lower === "stochastic")
                        values.push(["%K", indicators.stochastic.k[i]], ["%D", indicators.stochastic.d[i]]);
                    else if (settings.lower === "rsi" || settings.lower === "roc")
                        values.push([settings.lower.toUpperCase(), indicators[settings.lower][i]]);
                }
                return bar ? technicalTooltip(bar, values, markers.filter(signal => signal.date === bar.date).map(signal => `${signal.label}: ${signal.description}`)) : "";
            } },
        graphic: [{ type: "text", left: 8, top: 8, style: { text: "PRICE", fill: c.muted, fontSize: 9 } }, ...(settings.volume ? [{ type: "text" as const, left: 8, top: hasLower ? "55%" : "71%", style: { text: settings.volumeMA ? "VOLUME · MA20" : "VOLUME", fill: c.muted, fontSize: 9 } }] : []), ...(hasLower ? [{ type: "text" as const, left: 8, top: settings.volume ? "72%" : "60%", style: { text: settings.lower.toUpperCase(), fill: c.muted, fontSize: 9 } }] : [])],
        xAxis: grids.map((_, index) => ({ type: "category", gridIndex: index, data: dates, boundaryGap: true, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: index === grids.length - 1, hideOverlap: true, color: c.muted, fontSize: 10 }, axisPointer: { show: true, snap: true } })),
        yAxis: grids.map((_, index) => ({ type: "value", gridIndex: index, position: "right", scale: index === 0, min: index === lowerIndex && (settings.lower === "rsi" || settings.lower === "stochastic") ? 0 : undefined, max: index === lowerIndex && (settings.lower === "rsi" || settings.lower === "stochastic") ? 100 : undefined, splitNumber: index === 0 ? 5 : 2, axisLabel: { color: c.muted, fontSize: 10, formatter: (v: number) => index === volumeIndex ? new Intl.NumberFormat("en", { notation: "compact" }).format(v) : v.toFixed(2) }, splitLine: { lineStyle: { color: c.line } }, axisPointer: { label: { precision: 2 } } })),
        dataZoom: [{ id: "inside", type: "inside", xAxisIndex: grids.map((_, i) => i), start: zoom.start, end: zoom.end }, { id: "slider", type: "slider", xAxisIndex: grids.map((_, i) => i), start: zoom.start, end: zoom.end, bottom: 0, height: 16, showDetail: false, brushSelect: false, borderColor: c.line, fillerColor: "#1416190c", dataBackground: { lineStyle: { color: c.muted }, areaStyle: { color: c.line } } }], series };
}
