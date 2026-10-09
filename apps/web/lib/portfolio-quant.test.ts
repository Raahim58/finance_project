import { describe, expect, it } from "vitest";
import type { CapitalMarketAssumptions, EfficientFrontier, PortfolioQuant } from "@/lib/api";
import { comparePoints, delta, kpiFor, pctFraction, riskFreeRate, sharpeRatio, toCsv } from "./portfolio-quant";

const frontier = { markers: { current: { expected_return: 0.2, volatility: 0.1, weights: {} }, global_minimum_variance: { expected_return: 0.15, volatility: 0.08, weights: {} }, maximum_sharpe: null }, assumptions: { risk_free_rate: null } } as unknown as EfficientFrontier;
const quant = { portfolio: { max_drawdown: -0.17 }, benchmark: { available: false, symbol: "KSE100", reason: "No risk-free" } } as unknown as PortfolioQuant;

describe("portfolio quant helpers", () => {
  it("keeps missing inputs missing instead of defaulting to zero", () => {
    expect(pctFraction(null)).toBe("—");
    expect(pctFraction(0)).toBe("0.0%");
    expect(sharpeRatio(0.2, 0.1, null)).toBeNull();
    expect(sharpeRatio(0.2, 0, 0.1)).toBeNull();
    expect(sharpeRatio(0.2, 0.1, 0.1)).toBeCloseTo(1);
    expect(delta(null, 1)).toBeNull();
  });
  it("marks unavailable comparison points with a reason", () => {
    const points = comparePoints(frontier, null, quant);
    expect(points.find(point => point.id === "maximum_sharpe")).toMatchObject({ plottable: false });
    expect(points.find(point => point.id === "risk_free")).toMatchObject({ plottable: false });
    expect(points.find(point => point.id === "benchmark")?.reason).toBe("No risk-free");
    expect(points.find(point => point.id === "current")).toMatchObject({ plottable: true, expectedReturn: 0.2 });
  });
  it("reads the observed risk-free rate and only gives drawdown/beta to the current portfolio", () => {
    const assumptions = { risk_free: { annual_rate: 0.11 } } as unknown as CapitalMarketAssumptions;
    expect(riskFreeRate(assumptions, frontier)).toBe(0.11);
    const points = comparePoints(frontier, assumptions, quant);
    expect(kpiFor(points[0], 0.11, quant)).toMatchObject({ maxDrawdown: -0.17, beta: null });
    expect(kpiFor(points[1], 0.11, quant).maxDrawdown).toBeNull();
  });
  it("escapes CSV cells", () => {
    expect(toCsv([["a,b", 'q"x', null, 2]])).toBe('"a,b","q""x",,2');
  });
});
