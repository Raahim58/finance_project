export const technicalRanges = ["1M", "3M", "6M", "1Y", "3Y", "5Y", "MAX"] as const;
export type TechnicalRange = typeof technicalRanges[number];
const months: Record<Exclude<TechnicalRange, "MAX">, number> = { "1M": 1, "3M": 3, "6M": 6, "1Y": 12, "3Y": 36, "5Y": 60 };
export function rangeStart(end: string, range: TechnicalRange): string | undefined {
    if (range === "MAX")
        return undefined;
    const date = new Date(`${end}T00:00:00Z`), day = date.getUTCDate();
    date.setUTCDate(1);
    date.setUTCMonth(date.getUTCMonth() - months[range]);
    const last = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
    date.setUTCDate(Math.min(day, last));
    return date.toISOString().slice(0, 10);
}
export function historyRequest(end: string, range: TechnicalRange) {
    const start = rangeStart(end, range);
    // Extra observations before the visible range initialize indicators.
    const warmup = start ? new Date(Date.parse(start) - 550 * 86400000).toISOString().slice(0, 10) : undefined;
    return { startDate: warmup, endDate: end };
}
