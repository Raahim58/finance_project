import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearApiCache, getCompanies, getCompanyHistory, getPortfolioSummary, resumeAssistantExecution } from "./api";

describe("API GET cache", () => {
  beforeEach(() => {
    clearApiCache();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it("deduplicates concurrent requests and reuses the response", async () => {
    localStorage.setItem("psx_ai_token", "test-session");
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

  it("repairs a stale browser session and retries the protected request once", async () => {
    localStorage.setItem("psx_ai_token", "stale-session");
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: vi.fn().mockResolvedValue({ detail: "Invalid token" }),
      } as unknown as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ access_token: "fresh-sample-session" }),
      } as unknown as Response)
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: vi.fn().mockResolvedValue({ id: "portfolio-1" }),
      } as unknown as Response);

    await expect(getPortfolioSummary("portfolio-1")).resolves.toEqual({ id: "portfolio-1" });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[1][0]).toBe("/api/auth/sample-session");
    expect(localStorage.getItem("psx_ai_token")).toBe("fresh-sample-session");
    const retryHeaders = new Headers(fetchMock.mock.calls[2][1]?.headers);
    expect(retryHeaders.get("Authorization")).toBe("Bearer fresh-sample-session");
  });

  it("requests the complete stored company directory and five-year-sized history", async () => {
    localStorage.setItem("psx_ai_token", "test-session");
    const response = { ok: true, status: 200, json: vi.fn().mockResolvedValue([]) };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(response as unknown as Response);

    await getCompanies();
    await getCompanyHistory("MEBL");

    expect(fetchMock.mock.calls[0][0]).toBe("/api/market/companies?limit=1000");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/market/company/MEBL/history?limit=2000");
  });

  it("shows the sanitized provider diagnostic for a failed assistant run", async () => {
    localStorage.setItem("psx_ai_token", "test-session");
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({
        execution_id: "run-1",
        status: "failed",
        error_code: "provider_http_400",
        error_detail: "Invalid function declaration schema.",
        response: null,
      }),
    } as unknown as Response);

    await expect(resumeAssistantExecution("run-1")).rejects.toThrow(
      "Invalid function declaration schema.",
    );
  });
});
