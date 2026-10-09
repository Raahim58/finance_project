import type { Values } from "./types";
import { ema } from "./ema";
export function macd(values: Values, fast = 12, slow = 26, signalPeriod = 9) {
    if (fast >= slow)
        throw new RangeError("MACD fast period must be shorter than slow period");
    const fastEMA = ema(values, fast), slowEMA = ema(values, slow);
    const line = values.map((_, i) => fastEMA[i] == null || slowEMA[i] == null ? null : fastEMA[i]! - slowEMA[i]!);
    const signal = ema(line, signalPeriod);
    return { line, signal, histogram: line.map((value, i) => value == null || signal[i] == null ? null : value - signal[i]!) };
}
