import type { MacroRegime, MarketOverview, PortfolioPerformancePoint } from "@/lib/api";
import type { PortfolioEventIntelligence, ResearchEventView } from "@/lib/api/research";

export const signalFilters = ["All", "Price movers", "Volume", "Events", "Portfolio", "Macro"] as const;
export type SignalFilter = typeof signalFilters[number];
export type InvestigationSignal = {
  id: string;
  category: Exclude<SignalFilter, "All">;
  title: string;
  value: string;
  reason: string;
  source: string;
  date?: string | null;
  href: string;
  tone?: "positive" | "negative";
};

// Missing and malformed observations remain missing; never coerce them to zero.
export function numeric(value: unknown): number | null {
  if (value == null || value === "" || typeof value === "boolean") return null;
  if (typeof value !== "number" && typeof value !== "string") return null;
  if (typeof value === "string" && !value.trim()) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

export function formatNumber(value: unknown, digits = 2, compact = false) {
  const result = numeric(value);
  return result == null ? "—" : new Intl.NumberFormat("en-PK", {
    notation: compact ? "compact" : "standard", maximumFractionDigits: digits,
  }).format(result);
}

export function formatPercent(value: unknown, signed = true) {
  const result = numeric(value);
  return result == null ? "—" : `${signed && result > 0 ? "+" : ""}${result.toFixed(2)}%`;
}

export function formatDate(value?: string | null) {
  if (!value) return "Date unavailable";
  const date = new Date(value.length === 10 ? `${value}T00:00:00+05:00` : value);
  if (!Number.isFinite(date.getTime())) return "Date unavailable";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit", month: "short", year: "numeric", timeZone: "Asia/Karachi",
  }).format(date);
}

export function humanize(value: string) {
  return value.replaceAll("_", " ").replace(/^\w/, letter => letter.toUpperCase());
}

export function marketBreadth(market: MarketOverview | null) {
  if (!market?.sectors.length) return null;
  // Align breadth to the snapshot session; otherwise use its own latest date.
  const date = market.snapshot?.snapshot_date ?? [...market.sectors].map(row => row.trade_date).sort().at(-1);
  const rows = market.sectors.filter(row => row.trade_date === date);
  if (!rows.length) return null;
  const counts = rows.map(row => [numeric(row.advancers), numeric(row.decliners), numeric(row.unchanged)]);
  if (counts.some(row => row.some(value => value == null || value < 0))) return null;
  return {
    date,
    advancers: counts.reduce((sum, row) => sum + row[0]!, 0),
    decliners: counts.reduce((sum, row) => sum + row[1]!, 0),
    unchanged: counts.reduce((sum, row) => sum + row[2]!, 0),
    sources: [...new Set(rows.map(row => row.source))].join(" · "),
  };
}

export function performanceSeries(points: PortfolioPerformancePoint[]) {
  return [...points].sort((a, b) => a.value_date.localeCompare(b.value_date)).map(point => ({
    date: point.value_date, value: numeric(point.cumulative_twr_percent),
  }));
}

const MARKET_EVENT_TYPES = ["macro", "geopolitics"];
// Market-wide events have no instrument subject; they belong with macro, not company events.
export const isMarketEvent = (event: ResearchEventView) => MARKET_EVENT_TYPES.includes(event.event_type) && !event.subjects.length;

export function investigationSignals({ market, events, exposure, regime }: {
  market: MarketOverview | null; events: ResearchEventView[];
  exposure: PortfolioEventIntelligence | null; regime: MacroRegime | null;
}): InvestigationSignal[] {
  const signals: InvestigationSignal[] = [];
  const addMover = (rows: MarketOverview["top_gainers"], positive: boolean) => {
    rows.slice(0, 3).forEach((row, index) => {
      const change = numeric(row.change_percent);
      if (change == null || (positive ? change <= 0 : change >= 0)) return;
      signals.push({ id: `${positive ? "gain" : "loss"}:${row.symbol}`, category: "Price movers", title: row.symbol,
        value: formatPercent(change), reason: index === 0 ? `Largest ${positive ? "positive" : "negative"} daily move` : "Daily price mover",
        source: row.source, date: row.trade_date, href: `/companies/${encodeURIComponent(row.symbol)}`, tone: positive ? "positive" : "negative" });
    });
  };
  if (market) {
    addMover(market.top_gainers, true);
    addMover(market.top_losers, false);
    market.top_volume.slice(0, 3).forEach((row, index) => signals.push({
      id: `volume:${row.symbol}`, category: "Volume", title: row.symbol, value: formatNumber(row.volume, 1, true),
      reason: `#${index + 1} by traded volume`, source: row.source, date: row.trade_date,
      href: `/companies/${encodeURIComponent(row.symbol)}`,
    }));
  }
  const sourceOf = (event: ResearchEventView) => [...new Set(event.evidence.map(item => item.source_name))].join(" · ") || "Source unavailable";
  events.filter(event => !isMarketEvent(event)).slice(0, 8).forEach(event => signals.push({
    id: `event:${event.event_key}`, category: "Events", title: event.subjects.map(subject => subject.subject_key).join(", ") || humanize(event.event_type),
    value: humanize(event.event_type), reason: event.title,
    source: [...new Set(event.evidence.map(item => item.source_name))].join(" · ") || "Source unavailable",
    date: event.occurred_at, href: "/research",
  }));
  exposure?.events.slice(0, 3).forEach(row => {
    const weight = exposure.valuation_complete ? numeric(row.potentially_affected_weight) : null;
    signals.push({ id: `portfolio:${row.event.event_key}`, category: "Portfolio", title: exposure.portfolio_name,
      value: weight == null ? "Exposure unavailable" : `${formatPercent(weight * 100, false)} potentially exposed`,
      reason: row.event.title, source: row.companies.some(company => company.relationship_kind === "ai_proposed_indirect") ? "Includes AI-proposed indirect relevance" : "Event linked to holdings",
      date: row.event.occurred_at, href: `/portfolios/${encodeURIComponent(exposure.portfolio_id)}/research` });
  });
  events.filter(isMarketEvent).slice(0, 5).forEach(event => signals.push({
    id: `macro-event:${event.event_key}`, category: "Macro", title: humanize(event.event_type), value: "Market news",
    reason: event.title, source: sourceOf(event), date: event.occurred_at, href: "/research",
  }));
  if (regime && regime.regime !== "not_evaluated") signals.push({
    id: "macro", category: "Macro", title: "Macro", value: `${humanize(regime.regime)} regime`,
    reason: regime.method_note, source: "Rules-based assessment", href: "/market",
  });
  return signals;
}

export function visibleSignals(signals: InvestigationSignal[], filter: SignalFilter) {
  if (filter !== "All") return signals.filter(signal => signal.category === filter);
  return signalFilters.slice(1).flatMap(category => {
    const signal = signals.find(item => item.category === category);
    return signal ? [signal] : [];
  });
}
