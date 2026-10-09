import type { TechnicalBar, Values } from "./types";
import { sma, validatePeriod } from "./moving-average";
// Slow stochastic (14, 3, 3): raw %K, SMA3 %K, then SMA3 %D.
export function stochastic(bars: TechnicalBar[], period = 14, kSmoothing = 3, dSmoothing = 3) {
    validatePeriod(period);
    const raw: Values = bars.map((bar, i) => {
        if (i < period - 1)
            return null;
        const window = bars.slice(i - period + 1, i + 1), high = Math.max(...window.map(b => b.high)), low = Math.min(...window.map(b => b.low));
        return high === low ? null : 100 * (bar.close - low) / (high - low);
    });
    const k = sma(raw, kSmoothing), d = sma(k, dSmoothing);
    return { k, d };
}
