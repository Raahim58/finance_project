import type { HoldingSummary, MarketPrice, PortfolioPerformancePoint, PortfolioSummary, Transaction } from "@/lib/api";
import { numeric } from "@/lib/overview";
import { chartRanges, type ClosePoint } from "@/lib/markets";

export const overviewRanges = chartRanges;
export type OverviewRange = typeof chartRanges[number][0];

// Stored daily portfolio valuations; malformed values are dropped, never coerced to zero.
export function valuePoints(performance: PortfolioPerformancePoint[]): ClosePoint[] {
  return performance.flatMap(point => { const close = numeric(point.total_value); return close == null ? [] : [{ date: point.value_date, close }]; })
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function rangeSlice(points: ClosePoint[], range: OverviewRange): ClosePoint[] {
  const days = chartRanges.find(([label]) => label === range)?.[1];
  if (!days || !points.length) return points;
  const from = new Date(Date.parse(points[points.length - 1].date) - days * 86_400_000).toISOString().slice(0, 10);
  return points.filter(point => point.date >= from);
}

export type Closes = { date: string; close: number }[];
export const closesOf = (rows: MarketPrice[]): Closes => rows.flatMap(row => { const close = numeric(row.close); return close == null ? [] : [{ date: row.trade_date, close }]; })
  .sort((a, b) => a.date.localeCompare(b.date));

// One-year change from stored closes. Requires history reaching back at least ~11 months, otherwise null (unavailable).
export function oneYearChange(closes: Closes): number | null {
  const last = closes.at(-1);
  if (!last || closes.length < 2) return null;
  const target = new Date(Date.parse(last.date) - 365 * 86_400_000).toISOString().slice(0, 10);
  const base = [...closes].reverse().find(point => point.date <= target);
  const first = closes[0];
  const anchor = base ?? (Date.parse(last.date) - Date.parse(first.date) >= 335 * 86_400_000 ? first : null);
  return anchor && anchor.close > 0 ? (last.close / anchor.close - 1) * 100 : null;
}

export type HoldingRow = {
  symbol: string; name: string; sector: string; value: number | null; weight: number | null; price: number | null;
  dayPercent: number | null; dayChange: number | null; oneYear: number | null; trend: number[];
};

export function holdingRows(summary: PortfolioSummary, history: Record<string, Closes | undefined>): HoldingRow[] {
  const total = numeric(summary.total_value);
  return summary.holdings.map((holding: HoldingSummary) => {
    const value = numeric(holding.market_value), closes = history[holding.symbol] ?? [];
    return {
      symbol: holding.symbol, name: holding.name, sector: holding.sector, value,
      weight: value != null && total ? value / total * 100 : null, price: numeric(holding.latest_price),
      dayPercent: numeric(holding.day_change_percent), dayChange: numeric(holding.day_change),
      oneYear: oneYearChange(closes), trend: closes.slice(-30).map(point => point.close),
    };
  }).sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
}

// Rows with a known day change only; unpriced holdings are never ranked as zero.
export function movers(rows: HoldingRow[], count = 3) {
  const known = rows.filter(row => row.dayChange != null);
  return {
    contributors: known.filter(row => row.dayChange! > 0).sort((a, b) => b.dayChange! - a.dayChange!).slice(0, count),
    detractors: known.filter(row => row.dayChange! < 0).sort((a, b) => a.dayChange! - b.dayChange!).slice(0, count),
  };
}

const money = (value: number) => `PKR ${new Intl.NumberFormat("en-PK", { maximumFractionDigits: 0 }).format(Math.abs(value))}`;

// Template over stored numbers only; returns null when the day change is unavailable.
export function briefHeadline(name: string, dayPercent: number | null, dayChange: number | null, benchmark?: { name: string; percent: number | null } | null) {
  if (dayPercent == null) return null;
  const dir = dayPercent > 0 ? "up" : dayPercent < 0 ? "down" : "unchanged";
  const title = dir === "unchanged" ? `${name} unchanged today` : `${name} ${dir} ${Math.abs(dayPercent).toFixed(2)}% today`;
  const parts = [dayChange != null && dayChange !== 0 ? `The portfolio value ${dayChange > 0 ? "increased" : "decreased"} by ${money(dayChange)} on the latest stored session.` : "The latest stored session shows no change in portfolio value."];
  if (benchmark?.percent != null) {
    const diff = dayPercent - benchmark.percent;
    parts.push(`${benchmark.name} moved ${benchmark.percent > 0 ? "+" : ""}${benchmark.percent.toFixed(2)}%, so the portfolio ${diff > 0 ? "outperformed" : diff < 0 ? "underperformed" : "matched"} it${diff === 0 ? "" : ` by ${Math.abs(diff).toFixed(2)} percentage points`}.`);
  }
  return { title, text: parts.join(" ") };
}

export function activityLine(tx: Transaction): { title: string; text: string } {
  const type = tx.transaction_type.toLowerCase(), qty = numeric(tx.quantity), price = numeric(tx.price), amount = numeric(tx.amount);
  const verb = ({ buy: "Bought", sell: "Sold", dividend: "Dividend from", deposit: "Deposit", withdrawal: "Withdrawal", cash_in: "Cash in", cash_out: "Cash out" } as Record<string, string>)[type] ?? tx.transaction_type.replaceAll("_", " ");
  const fmt = (value: number) => new Intl.NumberFormat("en-PK", { maximumFractionDigits: 2 }).format(value);
  const title = tx.symbol && !["deposit", "withdrawal", "cash_in", "cash_out"].includes(type) ? `${verb} ${tx.symbol}` : verb;
  const text = qty != null && price != null ? `${fmt(qty)} shares at PKR ${fmt(price)}` : amount != null ? `PKR ${fmt(Math.abs(amount))}` : "Amount unavailable";
  return { title, text };
}
