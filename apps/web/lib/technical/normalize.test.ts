import { describe, expect, it } from "vitest";
import type { MarketPrice } from "@/lib/api/market";
import { candleValues, normalizePriceHistory } from "./normalize";
import { historyRequest, rangeStart } from "./ranges";
const row = (trade_date: string, close = "11"): MarketPrice => ({ symbol: "TEST", trade_date, open: "10", high: "12", low: "9", close, previous_close: "10", change: "1", change_percent: "10", volume: 100, value: "1100", source: "test", ingested_at: "2026-10-08T00:00:00Z" });
describe("OHLCV normalization", () => {
    it("sorts reverse API history and maps candles to OCLH", () => {
        const { bars } = normalizePriceHistory([row("2026-10-08"), row("2026-10-07", "10")]);
        expect(bars.map(bar => bar.date)).toEqual(["2026-10-07", "2026-10-08"]);
        expect(candleValues(bars)).toEqual([[10, 10, 9, 12], [10, 11, 9, 12]]);
        expect(bars.map(bar => bar.volume)).toEqual([100, 100]);
    });
    it("rejects malformed dates, missing prices, inconsistent OHLC and duplicates", () => {
        const result = normalizePriceHistory([row("2026-10-08"), row("2026-10-08"), row("2026-02-30"), row("2026-10-06", ""), row("2026-10-05", "20"), { ...row("2026-10-04"), volume: -1 }]);
        expect(result.bars).toHaveLength(1);
        expect(result.rejected).toBe(5);
    });
    it("keeps source metadata and missing change as null", () => {
        const { bars } = normalizePriceHistory([{ ...row("2026-10-08"), change_percent: "", source_url: "https://example.com" }]);
        expect(bars[0].changePercent).toBeNull();
        expect(bars[0].sourceUrl).toBe("https://example.com");
    });
});
describe("ranges", () => {
    it("clamps month ends and fetches warmup outside the visible range", () => {
        expect(rangeStart("2026-03-31", "1M")).toBe("2026-02-28");
        expect(rangeStart("2024-02-29", "1Y")).toBe("2023-02-28");
        expect(historyRequest("2026-10-08", "1M").startDate! < "2026-09-08").toBe(true);
        expect(historyRequest("2026-10-08", "MAX").startDate).toBeUndefined();
    });
});
