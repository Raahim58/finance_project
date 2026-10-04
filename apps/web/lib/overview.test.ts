import { describe, expect, it } from "vitest";
import type { MarketOverview, PortfolioPerformancePoint } from "@/lib/api";
import { formatPercent, investigationSignals, marketBreadth, numeric, performanceSeries, visibleSignals } from "./overview";

describe("overview data semantics", () => {
  it("keeps missing values distinct from observed zero", () => {
    for (const missing of [null, undefined, "", " ", false, "bad", NaN, Infinity]) expect(numeric(missing)).toBeNull();
    expect(formatPercent(null)).toBe("—");
    expect(formatPercent("0")).toBe("0.00%");
  });

  it("aggregates only breadth from the snapshot session", () => {
    const market = { snapshot: { snapshot_date: "2026-10-01" }, sectors: [
      { trade_date: "2026-10-01", advancers: 3, decliners: 2, unchanged: 1, source: "Observed source" },
      { trade_date: "2026-10-01", advancers: 4, decliners: 1, unchanged: 0, source: "Observed source" },
      { trade_date: "2026-09-30", advancers: 100, decliners: 100, unchanged: 100, source: "Old source" },
    ] } as MarketOverview;
    expect(marketBreadth(market)).toEqual({ date: "2026-10-01", advancers: 7, decliners: 3, unchanged: 1, sources: "Observed source" });
    expect(marketBreadth({ ...market, snapshot: { ...market.snapshot!, snapshot_date: "2026-10-02" } })).toBeNull();
    expect(marketBreadth({ ...market, sectors: [] })).toBeNull();
  });

  it("does not bridge a missing ledger return or scale percentage points twice", () => {
    const points = [
      { value_date: "2026-10-03", cumulative_twr_percent: null },
      { value_date: "2026-10-01", cumulative_twr_percent: "1.25" },
      { value_date: "2026-10-02", cumulative_twr_percent: "0" },
    ] as PortfolioPerformancePoint[];
    expect(performanceSeries(points)).toEqual([
      { date: "2026-10-01", value: 1.25 }, { date: "2026-10-02", value: 0 }, { date: "2026-10-03", value: null },
    ]);
  });

  it("does not invent signals from absent data or report incomplete exposure", () => {
    expect(investigationSignals({ market: null, events: [], exposure: null, regime: null })).toEqual([]);
    const signals = investigationSignals({ market: null, events: [], regime: null, exposure: {
      portfolio_id: "owned", portfolio_name: "Owned portfolio", valuation_complete: false, coverage: { holdings: 2, priced_holdings: 1 },
      events: [{ event: { id: "e", event_key: "raw:e", title: "Stored event", occurred_at: "2026-10-01", event_type: "rates", raw_event_id: "e", normalized_event_id: "n", source_document_type: "news", materiality: "high", freshness_status: "recent", factors: [], subjects: [], evidence: [] }, potentially_affected_weight: "0.25", companies: [] }],
    } });
    expect(signals[0].value).toBe("Exposure unavailable");
    expect(signals[0].href).toBe("/portfolios/owned/research");
    expect(visibleSignals(signals, "Portfolio")).toEqual(signals);
    expect(visibleSignals(signals, "Volume")).toEqual([]);
  });
});
