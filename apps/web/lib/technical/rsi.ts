import type { Values } from "./types";
import { validatePeriod } from "./moving-average";
export function rsi(values: Values, period = 14): Values {
    validatePeriod(period);
    let previous: number | null = null, gain = 0, loss = 0, count = 0;
    return values.map(value => {
        if (value == null) {
            previous = null;
            gain = 0;
            loss = 0;
            count = 0;
            return null;
        }
        if (previous == null) {
            previous = value;
            return null;
        }
        const delta = value - previous;
        previous = value;
        if (count < period) {
            gain += Math.max(0, delta);
            loss += Math.max(0, -delta);
            count++;
            if (count < period)
                return null;
            gain /= period;
            loss /= period;
        }
        else {
            gain = (gain * (period - 1) + Math.max(0, delta)) / period;
            loss = (loss * (period - 1) + Math.max(0, -delta)) / period;
        }
        return gain === 0 && loss === 0 ? 50 : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    });
}
