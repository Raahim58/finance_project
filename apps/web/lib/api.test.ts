import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearApiCache, getPortfolioSummary } from "./api";

describe("API GET cache", () => {
  beforeEach(() => {
    clearApiCache();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("deduplicates concurrent requests and reuses the response", async () => {
    const response = { ok: true, status: 200, json: vi.fn().mockResolvedValue({ id: "portfolio-1" }) };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response as unknown as Response);

    const [first, second] = await Promise.all([
      getPortfolioSummary("portfolio-1"),
      getPortfolioSummary("portfolio-1"),
    ]);
    const third = await getPortfolioSummary("portfolio-1");

    expect(first).toEqual({ id: "portfolio-1" });
    expect(second).toEqual(first);
    expect(third).toEqual(first);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
