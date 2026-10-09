import type { Values } from "./types";
import { sma } from "./moving-average";
export function bollinger(values: Values, period = 20, deviations = 2) {
    if (!Number.isFinite(deviations) || deviations < 0)
        throw new RangeError("Invalid deviation multiplier");
    const middle = sma(values, period);
    // Population standard deviation over the same complete trailing window as SMA.
    const spread = middle.map((mean, index) => mean == null ? null : Math.sqrt(values.slice(index - period + 1, index + 1).reduce<number>((sum, value) => sum + (value! - mean) ** 2, 0) / period) * deviations);
    return { middle, upper: middle.map((mean, i) => mean == null ? null : mean + spread[i]!), lower: middle.map((mean, i) => mean == null ? null : mean - spread[i]!) };
}
