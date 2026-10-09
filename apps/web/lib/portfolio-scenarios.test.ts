import { describe, expect, it } from "vitest";
import type { ScenarioResult } from "@/lib/api";
import { barWidth, customPayload, formatPkr, formatSigned, holdingImpacts, sectorImpacts, templateForRun } from "./portfolio-scenarios";

const result = {
  id: "r", name: "Rates +200 bps · 1", data_cutoff: "2026-08-07", shocks: {}, portfolio_value: 1000, stressed_portfolio_value: 940, pnl: -60, pnl_percent: -0.06,
  positions: [
    { symbol: "AAA", sector: "Banking", value: 400, shock: -0.1, pnl: -40, mapping_sources: ["sector"] },
    { symbol: "BBB", sector: "Cement", value: 200, shock: -0.1, pnl: -20, mapping_sources: ["sector"] },
    { symbol: "CCC", sector: "Tech", value: 100, shock: 0, pnl: 0, mapping_sources: [] },
  ],
  sector_contributions: { Banking: -40, Cement: -20, Tech: 0 }, compliance: { compliant: true, status: "PASS", checks: [], violations: [], not_evaluated: [] }, assumptions: [],
} as unknown as ScenarioResult;

describe("scenario result derivations", () => {
  it("computes weights and contributions on total portfolio value, flagging unmapped holdings", () => {
    const rows = holdingImpacts(result, { AAA: "Alpha" });
    expect(rows[0]).toMatchObject({ symbol: "AAA", name: "Alpha", weight: 0.4, contribution: -0.04 });
    expect(rows.find(row => row.symbol === "CCC")?.unmapped).toBe(true);
    expect(rows.find(row => row.symbol === "BBB")?.unmapped).toBe(false);
  });
  it("aggregates sector weight and sector impact from positions", () => {
    const rows = sectorImpacts(result);
    expect(rows[0]).toMatchObject({ sector: "Banking", weight: 0.4, impact: -0.1, contribution: -0.04 });
  });
  it("never invents values from missing data", () => {
    expect(holdingImpacts({ ...result, portfolio_value: 0 }, {})[0].weight).toBeNull();
    expect(formatSigned(null)).toBe("—");
    expect(barWidth(null, [1, 2])).toBe(0);
    expect(barWidth(-1, [-2, 1])).toBe(50);
  });
  it("formats signed values", () => {
    expect(formatSigned(-0.062)).toBe("-6.2%");
    expect(formatSigned(0.034, 1, " pp")).toBe("+3.4 pp");
    expect(formatPkr(-298260)).toBe("PKR -298,260");
  });
  it("matches template runs by name and version", () => {
    const templates = [{ id: "rate_shock", name: "Rates +200 bps", version: "1", description: "", sector_shocks: {}, factor_shocks: {}, required_mappings: [] }];
    expect(templateForRun(result.name, templates)?.id).toBe("rate_shock");
  });
  it("requires a complete shock for custom scenarios", () => {
    expect(customPayload({ symbol: "AAA", securityShock: "", sector: "", sectorShock: "", factor: "", factorShock: "" })).toHaveProperty("error");
    const built = customPayload({ symbol: "AAA", securityShock: "-10", sector: "", sectorShock: "", factor: "", factorShock: "" });
    expect(built).toMatchObject({ payload: { scenario_type: "sensitivity", shocks: { AAA: -0.1 } } });
  });
});
