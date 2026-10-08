import { describe, expect, it } from "vitest";
import { averagePairwiseCorrelation, concentrationRows, mandateRows, riskBrief, rollingSeries } from "./portfolio-risk";
import { topicEnabled } from "@/components/settings/providers";

describe("portfolio risk derivations", () => {
  it("averages only off-diagonal correlations", () => {
    expect(averagePairwiseCorrelation([[1, 0.5, 0.1], [0.5, 1, 0.3], [0.1, 0.3, 1]])).toBeCloseTo(0.3);
    expect(averagePairwiseCorrelation([])).toBeNull();
  });
  it("keeps missing values missing", () => {
    expect(concentrationRows(null, null).every(row => row.value === "—")).toBe(true);
  });
  it("slices rolling volatility by range from the last stored date", () => {
    const rolling = { points: [{ date: "2026-01-01", volatility: 0.1 }, { date: "2026-09-01", volatility: 0.2 }, { date: "2026-10-01", volatility: 0.3 }] } as never;
    expect(rollingSeries(rolling, "1M").map(p => p.date)).toEqual(["2026-09-01", "2026-10-01"]);
    expect(rollingSeries(rolling, "ALL")).toHaveLength(3);
  });
  it("maps compliance checks to rule rows with current values from exposure", () => {
    const rows = mandateRows({ compliant: false, violations: [], checks: [{ code: "max_instrument_weight", label: "Security concentration", status: "BREACH", limit: 0.15 }] }, { total_value: "1", by_company: [{ symbol: "ENGRO", name: "", market_value: "1", weight_percent: "18.1" }], by_sector: [] });
    expect(rows[0]).toMatchObject({ limit: "≤ 15.0%", current: "18.1%", status: "BREACH" });
  });
  it("states breaches and missing evaluation in the brief", () => {
    expect(riskBrief({ breaches: ["a", "b"], notEvaluated: 1, volatility: 0.182 }).join(" ")).toMatch(/2 mandate issues.*18\.2%.*1 check is not evaluated/);
  });
  it("shows unknown alert types and defaults topics on", () => {
    expect(topicEnabled({ data_freshness: false }, "stale_data")).toBe(false);
    expect(topicEnabled({}, "stale_data")).toBe(true);
    expect(topicEnabled({ mandate_breaches: false }, "something_new")).toBe(true);
  });
});
