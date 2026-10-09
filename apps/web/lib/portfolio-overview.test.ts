import { describe, expect, it } from "vitest";
import type { PortfolioSummary } from "@/lib/api";
import { activityLine, briefHeadline, holdingRows, movers, oneYearChange, rangeSlice, valuePoints } from "./portfolio-overview";

const day = (offset: number) => new Date(Date.UTC(2025, 0, 1) + offset * 86_400_000).toISOString().slice(0, 10);

describe("portfolio overview helpers", () => {
  it("drops malformed valuations and slices by range", () => {
    const points = valuePoints([{ value_date: "2025-03-01", total_value: "110" }, { value_date: "2025-01-01", total_value: "100" }, { value_date: "2025-02-01", total_value: "bad" }] as never);
    expect(points).toEqual([{ date: "2025-01-01", close: 100 }, { date: "2025-03-01", close: 110 }]);
    expect(rangeSlice(points, "1W")).toHaveLength(1);
    expect(rangeSlice(points, "ALL")).toHaveLength(2);
  });
  it("computes 1Y only with enough history", () => {
    const long = Array.from({ length: 400 }, (_, i) => ({ date: day(i), close: 100 + i }));
    expect(oneYearChange(long)).toBeCloseTo((499 / 134 - 1) * 100, 5);
    expect(oneYearChange(long.slice(-60))).toBeNull();
    expect(oneYearChange([])).toBeNull();
  });
  it("ranks movers without treating missing as zero", () => {
    const summary = { total_value: "1000", holdings: [
      { symbol: "A", name: "A", sector: "x", market_value: "600", latest_price: "10", day_change: "30", day_change_percent: "5" },
      { symbol: "B", name: "B", sector: "x", market_value: "300", latest_price: "10", day_change: "-10", day_change_percent: "-3" },
      { symbol: "C", name: "C", sector: "x", market_value: "100", latest_price: null, day_change: null, day_change_percent: null },
    ] } as unknown as PortfolioSummary;
    const rows = holdingRows(summary, {});
    expect(rows[0].weight).toBe(60);
    const { contributors, detractors } = movers(rows);
    expect(contributors.map(r => r.symbol)).toEqual(["A"]);
    expect(detractors.map(r => r.symbol)).toEqual(["B"]);
  });
  it("builds headline from numbers only", () => {
    expect(briefHeadline("Core", null, null)).toBeNull();
    const brief = briefHeadline("Core", 1.5, 70420, { name: "KSE-100", percent: 1.0 })!;
    expect(brief.title).toBe("Core up 1.50% today");
    expect(brief.text).toContain("PKR 70,420");
    expect(brief.text).toContain("outperformed it by 0.50 percentage points");
  });
  it("describes transactions", () => {
    expect(activityLine({ transaction_type: "buy", symbol: "OGDC", quantity: "50", price: "155.2", amount: "1" } as never)).toEqual({ title: "Bought OGDC", text: "50 shares at PKR 155.2" });
  });
});
