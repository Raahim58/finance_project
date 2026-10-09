import type { Values } from "./types";
export function validatePeriod(period: number) {
    if (!Number.isInteger(period) || period < 1)
        throw new RangeError("Period must be a positive integer");
}
export function sma(values: Values, period: number): Values {
    validatePeriod(period);
    let sum = 0, count = 0;
    return values.map((value, index) => {
        if (value != null) {
            sum += value;
            count++;
        }
        const old = values[index - period];
        if (index >= period && old != null) {
            sum -= old;
            count--;
        }
        return index >= period - 1 && count === period ? sum / period : null;
    });
}
