import type { MarketPrice } from "@/lib/api/market";
import type { TechnicalBar } from "./types";
const number = (value: unknown) => typeof value === "number" || typeof value === "string" && value.trim() !== "" ? Number(value) : NaN;
// Drop malformed observations; never interpolate or turn a quote into a candle.
export function normalizePriceHistory(rows: MarketPrice[]): {
    bars: TechnicalBar[];
    rejected: number;
} {
    let rejected = 0;
    const byDate = new Map<string, TechnicalBar>();
    for (const row of rows) {
        const open = number(row.open), high = number(row.high), low = number(row.low), close = number(row.close), volume = number(row.volume), date = row.trade_date;
        if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0, 10) !== date || ![open, high, low, close, volume].every(Number.isFinite) || low <= 0 || volume < 0 || high < Math.max(open, close, low) || low > Math.min(open, close)) {
            rejected++;
            continue;
        }
        if (byDate.has(date)) {
            rejected++;
            continue;
        }
        const change = number(row.change_percent);
        byDate.set(date, { date, open, high, low, close, volume, changePercent: Number.isFinite(change) ? change : null, source: row.source, sourceUrl: row.source_url, ingestedAt: row.ingested_at });
    }
    return { bars: [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date)), rejected };
}
// ECharts uses OCLH, not OHLC.
export const candleValues = (bars: TechnicalBar[]) => bars.map(bar => [bar.open, bar.close, bar.low, bar.high]);
