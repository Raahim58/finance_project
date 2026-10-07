import type { IndexClose } from "@/lib/api/market";
import { numeric } from "@/lib/overview";

export const chartRanges = [["1W", 7], ["1M", 31], ["3M", 92], ["1Y", 366], ["ALL", null]] as const;
export type ChartRange = typeof chartRanges[number][0];

export type ClosePoint = { date: string; close: number };

// Malformed closes are dropped, never coerced to zero.
export function closePoints(history: IndexClose[]): ClosePoint[] {
  return history.flatMap(row => { const close = numeric(row.close); return close == null ? [] : [{ date: row.trade_date, close }]; })
    .sort((a, b) => a.date.localeCompare(b.date));
}

const dayMs = 86_400_000;
const cutoff = (end: string, days: number) => new Date(Date.parse(end) - days * dayMs).toISOString().slice(0, 10);

export function sliceRange(points: ClosePoint[], range: ChartRange): ClosePoint[] {
  const days = chartRanges.find(([label]) => label === range)?.[1];
  if (!days || !points.length) return points;
  const from = cutoff(points[points.length - 1].date, days);
  return points.filter(point => point.date >= from);
}

// Highest and lowest stored close over the trailing 52 weeks; null when no history covers it.
export function yearExtremes(points: ClosePoint[]): { high: ClosePoint; low: ClosePoint } | null {
  const window = sliceRange(points, "1Y");
  if (!window.length) return null;
  return {
    high: window.reduce((best, point) => point.close > best.close ? point : best),
    low: window.reduce((best, point) => point.close < best.close ? point : best),
  };
}

export function timeAgo(value: string, now = Date.now()): string {
  const then = Date.parse(value);
  if (!Number.isFinite(then)) return "Date unavailable";
  const minutes = Math.max(0, Math.round((now - then) / 60_000));
  if (minutes < 60) return `${minutes || 1} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return days < 31 ? `${days} day${days === 1 ? "" : "s"} ago` : new Date(then).toLocaleDateString("en-PK", { day: "numeric", month: "short", year: "numeric" });
}

// Hostname of a stored company website, or null if it is absent or unparseable.
export function websiteHost(url?: string | null): string | null {
  if (!url?.trim()) return null;
  try { return new URL(/^https?:\/\//i.test(url) ? url : `https://${url}`).hostname.replace(/^www\./, "") || null; }
  catch { return null; }
}
