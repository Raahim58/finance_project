import { describe, expect, it } from "vitest";
import { closePoints, sliceRange, timeAgo, websiteHost, yearExtremes } from "./markets";

const history = [
  { trade_date: "2026-01-05", close: "100" }, { trade_date: "2026-03-01", close: "120" },
  { trade_date: "2026-03-20", close: "bad" }, { trade_date: "2026-03-25", close: "90" },
];

describe("markets helpers", () => {
  it("drops malformed closes", () => expect(closePoints(history).map(p => p.close)).toEqual([100, 120, 90]));
  it("slices relative to the latest stored date", () => expect(sliceRange(closePoints(history), "1W").map(p => p.date)).toEqual(["2026-03-25"]));
  it("finds 52w extremes", () => { const e = yearExtremes(closePoints(history)); expect([e?.high.close, e?.low.close]).toEqual([120, 90]); });
  it("returns null extremes without data", () => expect(yearExtremes([])).toBeNull());
  it("formats relative time", () => expect(timeAgo("2026-03-25T10:00:00Z", Date.parse("2026-03-25T12:00:00Z"))).toBe("2 hours ago"));
  it("extracts website hosts", () => { expect(websiteHost("https://www.hbl.com/about")).toBe("hbl.com"); expect(websiteHost(null)).toBeNull(); });
});
