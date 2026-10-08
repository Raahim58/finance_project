import { describe, expect, it } from "vitest";
import type { CapitalMarketAssumptions, EfficientFrontier } from "@/lib/api";
import { frontierOption } from "./chartOptions";

describe("frontier chart evidence", () => {
  const frontier = { points: [{ volatility: 0.24, expected_return: 0.18 }, { volatility: 0.12, expected_return: 0.11 }] } as EfficientFrontier;
  it("plots only returned model points and observed security estimates", () => {
    const assumptions = { securities: [{ symbol: "FFC", volatility: 0.2, expected_return: 0.17 }, { symbol: "MISSING", volatility: null, expected_return: 0.3 }] } as CapitalMarketAssumptions;
    const option = frontierOption(frontier, assumptions, [], true);
    expect(option.series[0].data).toEqual([[0.12, 0.11], [0.24, 0.18]]);
    expect(option.series[1].data).toEqual([{ name: "FFC", value: [0.2, 0.17] }]);
    expect(option.series).toHaveLength(2);
  });
  it("keeps unavailable comparators off the plot without inventing a substitute", () => {
    const option = frontierOption(frontier, null, [{ id: "maximum_sharpe", label: "Maximum Sharpe", tone: "alternative", plottable: false, volatility: null, expectedReturn: null }] , false);
    expect(option.series).toHaveLength(1);
  });
});
