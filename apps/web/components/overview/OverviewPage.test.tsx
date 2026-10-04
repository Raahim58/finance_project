import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Portfolio, PortfolioSummary } from "@/lib/api";
import { getAlerts, getIpsCompliance, getMacroRegime, getMarketFreshness, getMarketOverview, getPortfolioPerformance, getPortfolioSummary, getPortfolios } from "@/lib/api";
import { getEventFeed, getPortfolioEventIntelligence } from "@/lib/api/research";
import { OverviewPage } from "./OverviewPage";

vi.mock("@/lib/api", () => ({ getAlerts: vi.fn(), getIpsCompliance: vi.fn(), getMacroRegime: vi.fn(), getMarketFreshness: vi.fn(), getMarketOverview: vi.fn(), getPortfolioPerformance: vi.fn(), getPortfolioSummary: vi.fn(), getPortfolios: vi.fn(), getCompanies: vi.fn(), clearApiCache: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ request: vi.fn().mockResolvedValue({ full_name: "Fixture Reader", email: "reader@example.test" }) }));
vi.mock("@/lib/api/research", () => ({ getEventFeed: vi.fn(), getPortfolioEventIntelligence: vi.fn() }));
vi.mock("@/components/AssistantWorkspace", () => ({ useAssistantWorkspace: () => null }));
vi.mock("@/components/ResearchEventCard", () => ({ EvidenceDrawer: () => null }));
vi.mock("echarts-for-react", () => ({ default: () => <div data-testid="performance-chart" /> }));
const portfolio = { id: "first", name: "Backend portfolio", base_currency: "PKR", source_mode: "manual", is_default: true, history_complete: true } as Portfolio;
const summary = { portfolio, total_value: "123456", day_change: "125", day_change_percent: "0.1", cash_balance: "12345.6", holdings: [], valuation_complete: true, unpriced_symbols: [], data_source: "Observed fixture", data_freshness_date: "2026-10-01" } as unknown as PortfolioSummary;
afterEach(cleanup);
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getPortfolios).mockResolvedValue([portfolio, { ...portfolio, id: "second", name: "Second backend portfolio", is_default: false }]);
  vi.mocked(getPortfolioSummary).mockResolvedValue(summary);
  vi.mocked(getPortfolioPerformance).mockResolvedValue([]);
  vi.mocked(getAlerts).mockResolvedValue([{ classification: "monitoring_warning" }]);
  vi.mocked(getIpsCompliance).mockResolvedValue({ status: "PASS", compliant: true, checks: [], violations: [], not_evaluated: [] });
  vi.mocked(getPortfolioEventIntelligence).mockResolvedValue({ portfolio_id: "first", portfolio_name: portfolio.name, events: [], valuation_complete: true, coverage: { holdings: 0, priced_holdings: 0 } });
  vi.mocked(getMarketOverview).mockResolvedValue({ snapshot: null, top_gainers: [], top_losers: [], top_volume: [], sectors: [] });
  vi.mocked(getMarketFreshness).mockResolvedValue({ market_data_mode: "live", refresh_seconds: 60, is_stale: false, fallback_provider_active: false, trade_date_status: "current", exchange_session_status: "closed" });
  vi.mocked(getEventFeed).mockResolvedValue({ events: [], next_cursor: null });
  vi.mocked(getMacroRegime).mockResolvedValue({ regime: "not_evaluated", method: "rule_based_v1", method_note: "Missing observations", dimensions: {}, stress_signals: [], suggested_scenario_ids: [] });
});

describe("backend-driven Overview", () => {
  it("renders backend values and keeps monitoring warnings separate from mandate compliance", async () => {
    render(<OverviewPage />);
    await screen.findByText("PKR 123,456");
    expect(screen.getByText("1 active monitoring warning")).toBeInTheDocument();
    expect(screen.getByText("Mandate: within evaluated limits")).toBeInTheDocument();
    expect(screen.getByText("10.00%")).toBeInTheDocument();
    expect(screen.queryByText("124,735.36")).not.toBeInTheDocument();
    expect(getAlerts).toHaveBeenCalledWith("first", "active");
  });

  it("keeps global data available when portfolio valuation fails", async () => {
    vi.mocked(getPortfolioSummary).mockRejectedValue(new Error("Valuation service unavailable"));
    render(<OverviewPage />);
    await screen.findByText(/Portfolio valuation unavailable.*Valuation service unavailable/);
    expect(screen.getByRole("heading", { name: "Market snapshot" })).toBeInTheDocument();
    expect(screen.getByText("Market snapshot unavailable.")).toBeInTheDocument();
  });

  it("does not select an arbitrary portfolio when no default exists", async () => {
    vi.mocked(getPortfolios).mockResolvedValue([{ ...portfolio, is_default: false }]);
    render(<OverviewPage />);
    await screen.findByRole("option", { name: portfolio.name });
    expect(getPortfolioSummary).not.toHaveBeenCalled();
    expect(screen.getByText("Select a portfolio to see value and performance.")).toBeInTheDocument();
  });

  it("ignores a late previous-portfolio response after changing scope", async () => {
    let resolveFirst!: (value: PortfolioSummary) => void;
    vi.mocked(getPortfolioSummary).mockImplementation(id => id === "first" ? new Promise(resolve => { resolveFirst = resolve; }) : Promise.resolve({ ...summary, portfolio: { ...portfolio, id: "second", name: "Second backend portfolio" }, total_value: "987654" }));
    render(<OverviewPage />);
    await waitFor(() => expect(getPortfolioSummary).toHaveBeenCalledWith("first"));
    fireEvent.change(screen.getByLabelText("Overview portfolio"), { target: { value: "second" } });
    await screen.findByText("PKR 987,654");
    await act(async () => resolveFirst(summary));
    expect(screen.queryByText("PKR 123,456")).not.toBeInTheDocument();
    expect(screen.getByText("PKR 987,654")).toBeInTheDocument();
  });

  it("does not publish cash weights from a partial valuation", async () => {
    vi.mocked(getPortfolioSummary).mockResolvedValue({ ...summary, valuation_complete: false, unpriced_symbols: ["UNPRICED"] });
    render(<OverviewPage />);
    await screen.findByText(/Partial valuation/);
    expect(screen.queryByText("10.00%")).not.toBeInTheDocument();
  });
});
