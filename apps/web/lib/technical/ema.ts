import type { Values } from "./types";
import { validatePeriod } from "./moving-average";
// SMA-seeded EMA. A missing input restarts initialization, rather than filling a gap.
export function ema(values: Values, period: number): Values {
    validatePeriod(period);
    const alpha = 2 / (period + 1);
    let previous: number | null = null, sum = 0, count = 0;
    return values.map(value => {
        if (value == null) {
            previous = null;
            sum = 0;
            count = 0;
            return null;
        }
        if (previous == null) {
            sum += value;
            count++;
            if (count < period)
                return null;
            previous = sum / period;
        }
        else
            previous = alpha * value + (1 - alpha) * previous;
        return previous;
    });
}
