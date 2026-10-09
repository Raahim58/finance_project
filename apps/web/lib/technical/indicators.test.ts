import { describe, expect, it } from "vitest";
import { sma } from "./moving-average";
import { ema } from "./ema";
import { bollinger } from "./bollinger";
import { macd } from "./macd";
import { rsi } from "./rsi";
import { roc } from "./roc";
import { stochastic } from "./stochastic";
import { technicalSeries } from "./series";
import type { TechnicalBar } from "./types";
const bars = (values: number[]): TechnicalBar[] => values.map((close, i) => ({ date: `2026-01-${String(i + 1).padStart(2, "0")}`, open: close, high: close + 1, low: close - 1, close, volume: 10, changePercent: null, source: "test" }));
describe("deterministic indicators", () => {
    it("SMA requires complete trailing windows", () => {
        expect(sma([1, 2, 3, 4, 5], 3)).toEqual([null, null, 2, 3, 4]);
        expect(sma([1, null, 3, 4, 5], 3)).toEqual([null, null, null, null, 4]);
    });
    it("EMA uses an SMA seed and the standard alpha", () => {
        expect(ema([1, 2, 3, 4, 8], 3)).toEqual([null, null, 2, 3, 5.5]);
        expect(ema([1, 2, null, 3, 4, 5], 3)).toEqual([null, null, null, null, null, 4]);
    });
    it("Bollinger uses population deviation, including zero spread", () => {
        const bb = bollinger([1, 2, 3], 3, 2);
        expect(bb.middle).toEqual([null, null, 2]);
        expect(bb.upper[2]).toBeCloseTo(2 + 2 * Math.sqrt(2 / 3));
        expect(bb.lower[2]).toBeCloseTo(2 - 2 * Math.sqrt(2 / 3));
        expect(bollinger([5, 5, 5], 3).upper[2]).toBe(5);
    });
    it("MACD aligns the fast, slow and signal warmup", () => {
        const result = macd([1, 2, 3, 4, 5, 6], 2, 3, 2);
        expect(result.line).toEqual([null, null, .5, .5, .5, .5]);
        expect(result.signal).toEqual([null, null, null, .5, .5, .5]);
        expect(result.histogram).toEqual([null, null, null, 0, 0, 0]);
        const defaults = macd(Array.from({ length: 40 }, (_, i) => i + 1));
        expect(defaults.line.findIndex(v => v !== null)).toBe(25);
        expect(defaults.signal.findIndex(v => v !== null)).toBe(33);
    });
    it("RSI uses Wilder smoothing and handles flat, rising and falling prices", () => {
        expect(rsi([1, 2, 3, 4], 3)).toEqual([null, null, null, 100]);
        expect(rsi([4, 3, 2, 1], 3)).toEqual([null, null, null, 0]);
        expect(rsi([4, 4, 4, 4], 3)).toEqual([null, null, null, 50]);
        const result = rsi([1, 2, 1, 2, 1], 3);
        expect(result[3]).toBeCloseTo(66.6666667);
        expect(result[4]).toBeCloseTo(44.4444444);
    });
    it("ROC is a percentage over the configured lag", () => {
        expect(roc([10, 11, 12, 15], 2)).toEqual([null, null, 19.999999999999996, 36.36363636363635]);
        expect(roc([0, 2], 1)[1]).toBeNull();
    });
    it("slow stochastic smooths %K then %D and waits for both windows", () => {
        const result = stochastic(bars([2, 3, 4, 5, 6, 7]), 3, 2, 2);
        expect(result.k.slice(0, 3)).toEqual([null, null, null]);
        expect(result.k[3]).toBe(75);
        expect(result.d[3]).toBeNull();
        expect(result.d[4]).toBe(75);
        const flat = bars([2, 2, 2]).map(b => ({ ...b, high: 2, low: 2 }));
        expect(stochastic(flat, 2, 1, 1).k).toEqual([null, null, null]);
    });
    it("insufficient history never becomes an artificial zero", () => {
        const result = technicalSeries(bars(Array.from({ length: 18 }, () => 10)));
        expect(result.ma50.every(v => v === null)).toBe(true);
        expect(result.bollinger.upper.every(v => v === null)).toBe(true);
        expect(result.macd.line.every(v => v === null)).toBe(true);
    });
    it("rejects invalid parameters", () => {
        expect(() => sma([1], 0)).toThrow();
        expect(() => ema([1], 1.5)).toThrow();
        expect(() => bollinger([1], 2, -1)).toThrow();
        expect(() => macd([1], 26, 12)).toThrow();
    });
});
