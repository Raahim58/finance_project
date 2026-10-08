import type { Values } from "./types";
import { validatePeriod } from "./moving-average";
export function roc(values: Values, period = 12): Values {
    validatePeriod(period);
    return values.map((value, i) => value == null || i < period || values[i - period] == null || values[i - period] === 0 ? null : (value / values[i - period]! - 1) * 100);
}
