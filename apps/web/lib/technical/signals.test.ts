import { describe, expect, it } from "vitest";
import { crossing, detectSignals, visibleSignals } from "./signals";
import { technicalSeries } from "./series";
import { supportResistance, levelDefaults } from "./support-resistance";
import type { TechnicalBar } from "./types";
const bars = (closes: number[]): TechnicalBar[] => closes.map((close, i) => ({ date: new Date(Date.UTC(2026, 0, i + 1)).toISOString().slice(0, 10), open: close, close, high: close + 1, low: close - 1, volume: 10, source: "test", changePercent: null }));
describe("event detection", () => {
    it("crosses only on transitions, including equality and warmup", () => {
        expect(crossing(0, 1, 0, 0)).toBe("up");
        expect(crossing(1, 2, 0, 0)).toBeNull();
        expect(crossing(0, -1, 0, 0)).toBe("down");
        expect(crossing(null, 1, 0, 0)).toBeNull();
    });
    it("emits one Bollinger event and MACD event while the state persists", () => {
        const data = bars([9, 11, 12, 8, 7]), series = technicalSeries(data);
        series.bollinger.upper = [10, 10, 10, 10, 10];
        series.bollinger.lower = [9, 9, 9, 9, 9];
        series.macd.line = [0, 1, 2, -1, -2];
        series.macd.signal = [0, 0, 0, 0, 0];
        const signals = detectSignals(data, series);
        expect(signals.filter(s => s.type === "bollinger_upper_break").map(s => s.date)).toEqual([data[1].date]);
        expect(signals.filter(s => s.type === "bollinger_lower_break").map(s => s.date)).toEqual([data[3].date]);
        expect(signals.filter(s => s.pane === "macd").map(s => s.date)).toEqual([data[1].date, data[3].date]);
    });
    it("emits a volume threshold crossing once and restarts after returning below", () => {
        const data = bars([10, 10, 10, 10, 10]);
        data.forEach((bar, i) => bar.volume = [10, 30, 40, 10, 30][i]);
        const series = technicalSeries(data);
        series.volumeMA = [10, 10, 10, 10, 10];
        const signals = detectSignals(data, series).filter(s => s.type === "volume_spike");
        expect(signals.map(s => s.date)).toEqual([data[1].date, data[4].date]);
        expect(signals.every(s => s.pane === "volume")).toBe(true);
        expect(() => detectSignals(data, series, [], 1)).toThrow();
    });
    it("uses real volume MA20 warmup", () => {
        const data = bars(Array.from({ length: 25 }, () => 10));
        data[20].volume = 100;
        data[21].volume = 100;
        expect(detectSignals(data, technicalSeries(data)).filter(s => s.type === "volume_spike").map(s => s.date)).toEqual([data[20].date]);
    });
    it("uses the previous session’s established level and never an unconfirmed future level", () => {
        const data = bars([9, 11, 12]), series = technicalSeries(data);
        const level = { id: "test", value: 10, touches: 2, establishedIndex: 0, lastTouchIndex: 0, score: 4 };
        expect(detectSignals(data, series, [[level], [level], [level]]).filter(s => s.type === "resistance_breakout").map(s => s.date)).toEqual([data[1].date]);
        expect(detectSignals(data, series, [[], [], [level]]).filter(s => s.type === "resistance_breakout")).toHaveLength(0);
    });
    it("keeps markers on active panes and caps their visual density", () => {
        const data = bars(Array.from({ length: 60 }, (_, i) => i % 2 ? 12 : 9)), series = technicalSeries(data);
        series.bollinger.upper = data.map(() => 10);
        series.macd.line = data.map((_, i) => i % 2 ? 1 : -1);
        series.macd.signal = data.map(() => 0);
        const signals = detectSignals(data, series);
        expect(visibleSignals(signals, { overlays: ["bollinger"], lower: "none", volume: false, signals: true })).toHaveLength(12);
        expect(visibleSignals(signals, { overlays: [], lower: "macd", volume: false, signals: true }).every(s => s.pane === "macd")).toBe(true);
        expect(visibleSignals(signals, { overlays: ["bollinger"], lower: "macd", volume: true, signals: false })).toEqual([]);
    });
});
describe("pivot levels", () => {
    it("waits for right-hand confirmation and two touches", () => {
        const data = bars([8, 9, 12, 9, 8, 9, 12, 9, 8]);
        const config = { ...levelDefaults, pivotRadius: 1, maxDistanceFraction: 1 };
        const levels = supportResistance(data, config);
        expect(levels[6]).toEqual([]);
        expect(levels[7].some(level => level.value === 13 && level.touches === 2)).toBe(true);
    });
    it("is causal: adding future bars cannot change past levels or signals", () => {
        const data = bars(Array.from({ length: 80 }, (_, i) => 10 + Math.sin(i) * 2));
        const full = supportResistance(data), prefix = supportResistance(data.slice(0, 50));
        expect(full.slice(0, 50)).toEqual(prefix);
        expect(detectSignals(data, technicalSeries(data), full).filter(s => s.date <= data[49].date)).toEqual(detectSignals(data.slice(0, 50), technicalSeries(data.slice(0, 50)), prefix));
        expect(full.every(levels => levels.length <= 4)).toBe(true);
    });
});
