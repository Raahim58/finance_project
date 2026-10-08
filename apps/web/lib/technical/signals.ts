import type { TechnicalBar, TechnicalSignal, Values } from "./types";
import type { TechnicalSeries } from "./series";
import type { PriceLevel } from "./support-resistance";
export const signalDefaults = { volumeMultiplier: 2, maxVisiblePerPane: 12 };
export function crossing(previous: number | null, current: number | null, previousReference: number | null, currentReference: number | null): "up" | "down" | null {
    if (previous == null || current == null || previousReference == null || currentReference == null)
        return null;
    if (previous <= previousReference && current > currentReference)
        return "up";
    if (previous >= previousReference && current < currentReference)
        return "down";
    return null;
}
export function detectSignals(bars: TechnicalBar[], series: TechnicalSeries, levels: PriceLevel[][] = [], volumeMultiplier = signalDefaults.volumeMultiplier): TechnicalSignal[] {
    if (!Number.isFinite(volumeMultiplier) || volumeMultiplier <= 1)
        throw new RangeError("Volume multiplier must exceed one");
    const signals: TechnicalSignal[] = [];
    for (let i = 1; i < bars.length; i++) {
        const bar = bars[i], previous = bars[i - 1];
        const add = (type: TechnicalSignal["type"], pane: TechnicalSignal["pane"], value: number, label: string, description: string, suffix = "") => signals.push({ id: `${type}:${bar.date}${suffix}`, date: bar.date, type, pane, value, label, description });
        const macd = crossing(series.macd.line[i - 1], series.macd.line[i], series.macd.signal[i - 1], series.macd.signal[i]);
        if (macd)
            add(macd === "up" ? "macd_bullish_cross" : "macd_bearish_cross", "macd", series.macd.line[i]!, `MACD ${macd === "up" ? "bullish" : "bearish"} crossover`, `MACD crossed ${macd === "up" ? "above" : "below"} its signal line.`);
        const band = (values: Values, direction: "up" | "down") => crossing(previous.close, bar.close, values[i - 1], values[i]) === direction;
        if (band(series.bollinger.upper, "up"))
            add("bollinger_upper_break", "price", bar.close, "Bollinger upper-band crossing", "Close crossed above the upper Bollinger band (20, 2).");
        if (band(series.bollinger.lower, "down"))
            add("bollinger_lower_break", "price", bar.close, "Bollinger lower-band crossing", "Close crossed below the lower Bollinger band (20, 2).");
        if (crossing(previous.volume, bar.volume, series.volumeMA[i - 1] == null ? null : series.volumeMA[i - 1]! * volumeMultiplier, series.volumeMA[i] == null ? null : series.volumeMA[i]! * volumeMultiplier) === "up")
            add("volume_spike", "volume", bar.volume, "Volume threshold crossing", `Volume crossed above ${volumeMultiplier}× its 20-session moving average.`);
        for (const level of levels[i - 1] ?? []) {
            const direction = crossing(previous.close, bar.close, level.value, level.value);
            if (direction)
                add(direction === "up" ? "resistance_breakout" : "support_breakdown", "price", bar.close, direction === "up" ? "Resistance crossing" : "Support crossing", `Close crossed ${direction === "up" ? "above" : "below"} an established pivot cluster at PKR ${level.value.toFixed(2)} (${level.touches} touches).`, `: ${level.id}`);
        }
    }
    return signals;
}
// Visual thinning affects presentation only; the detector retains every event.
export function visibleSignals(signals: TechnicalSignal[], settings: {
    overlays: string[];
    lower: string;
    volume: boolean;
    signals: boolean;
}) {
    if (!settings.signals)
        return [];
    const eligible = signals.filter(s => s.pane === "macd" ? settings.lower === "macd" : s.pane === "volume" ? settings.volume : s.type.startsWith("bollinger") ? settings.overlays.includes("bollinger") : settings.overlays.includes("levels"));
    return (["price", "volume", "macd"] as const).flatMap(pane => eligible.filter(s => s.pane === pane).slice(-signalDefaults.maxVisiblePerPane));
}
