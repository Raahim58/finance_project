import { describe, expect, it } from "vitest";
import { buildInsights, buildRows, ipsFit, sectorSegments } from "./portfolio-build";

describe("build helpers", () => {
  it("ranks by current weight and rolls the tail into Others", () => {
    const current = { A: 0.5, B: 0.3, C: 0.15, CASH: 0.05 };
    const result = buildRows(current, { A: 0.4, B: 0.3, C: 0.1, D: 0.2 }, 2);
    expect(result.rows.map(row => row.symbol)).toEqual(["A", "B"]);
    expect(result.others?.count).toBe(3);
    expect(result.others?.current).toBeCloseTo(0.2);
    expect(result.others?.proposed).toBeCloseTo(0.3);
    expect(buildRows(current, current, null).others).toBeNull();
  });
  it("collapses sector tail", () => {
    const segments = sectorSegments({ E: 0.4, B: 0.2, M: 0.15, T: 0.1, X: 0.1, Y: 0.05 });
    expect(segments.at(-1)).toEqual({ label: "Others", value: 0.15000000000000002 });
    expect(segments).toHaveLength(5);
  });
  it("computes IPS fit over evaluated checks only", () => {
    const fit = ipsFit({ checks: [{ status: "PASS" }, { status: "BREACH" }, { status: "NOT_EVALUATED" }, { status: "PASS" }] });
    expect(fit).toMatchObject({ passed: 2, evaluated: 3, notEvaluated: 1 });
    expect(fit.ratio).toBeCloseTo(2 / 3);
    expect(ipsFit(null).ratio).toBeNull();
  });
  it("returns no insights without a comparison", () => {
    expect(buildInsights(null, [], null)).toBeNull();
  });
});
