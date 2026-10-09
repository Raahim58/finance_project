import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { decideRecommendation, getAlerts, getPortfolios, getRecommendations, type Portfolio } from "@/lib/api";
import { request } from "@/lib/api/client";
import { MonitoringWorkspace } from "./MonitoringWorkspace";

vi.mock("@/lib/api", () => ({ acknowledgeAlert: vi.fn(), getAlerts: vi.fn(), getPortfolios: vi.fn(), getRecommendations: vi.fn(), decideRecommendation: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ request: vi.fn() }));
vi.mock("@/components/AssistantWorkspace", () => ({ useAssistantWorkspace: () => null }));
vi.mock("@/components/WorkspaceHeader", () => ({ WorkspaceHeader: ({ children }: { children: React.ReactNode }) => <header>{children}</header> }));

const portfolios = [{ id: "p1", name: "First portfolio" }, { id: "p2", name: "Second portfolio" }] as Portfolio[];
const review = {
  id: "review-1", portfolio_id: "p1", message: "Review concentration", status: "open",
  trigger_label: "Position weight", evidence: { rule_type: "position_weight", current_value: 0.4, source: "Stored fixture" },
  freshness: { market_as_of: "2026-10-09" }, linked_allocation: { id: "allocation-1", version: 2 },
  uncertainty: { note: "Recompute risk before acting." },
};

afterEach(cleanup);
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getPortfolios).mockResolvedValue(portfolios);
  vi.mocked(getAlerts).mockResolvedValue([]);
  vi.mocked(request).mockResolvedValue([]);
  vi.mocked(getRecommendations).mockResolvedValue([review, { ...review, id: "review-2", portfolio_id: "p2", message: "Review IPS breach" }]);
  vi.mocked(decideRecommendation).mockImplementation(async (id, status) => ({ id, status }));
});

async function openReviews() {
  render(<MonitoringWorkspace />);
  expect(getRecommendations).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Reviews" }));
  await screen.findByRole("button", { name: "Review concentration" });
}

it("moves stored evidence and Build links into Monitoring while retaining the shared portfolio scope", async () => {
  await openReviews();
  expect(screen.getByRole("link", { name: "Open linked proposal →" })).toHaveAttribute("href", "/portfolios/p1/build?recommendation=review-1");
  expect(screen.getByText(/Stored fixture/)).toBeInTheDocument();
  expect(screen.getAllByText("Recompute risk before acting.").length).toBeGreaterThan(0);
  expect(screen.queryByText("Proposed portfolio impact")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Review portfolio"), { target: { value: "p2" } });
  expect(screen.queryByRole("button", { name: "Review concentration" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open linked proposal →" })).toHaveAttribute("href", "/portfolios/p2/build?recommendation=review-2");
  fireEvent.click(screen.getByRole("button", { name: "Alerts" }));
  expect(screen.getByLabelText("Monitoring portfolio")).toHaveValue("p2");
  await waitFor(() => expect(getAlerts).toHaveBeenCalledWith("p2", "active"));
});

it.each([["Mark reviewed", "reviewed"], ["Reject", "rejected"], ["Dismiss", "dismissed"], ["Resolve", "resolved"]] as const)("preserves the %s transition on the existing record", async (label, status) => {
  await openReviews();
  fireEvent.click(screen.getByRole("button", { name: label }));
  await waitFor(() => expect(decideRecommendation).toHaveBeenCalledWith("review-1", status));
  await waitFor(() => expect(screen.getByLabelText("Review status")).toHaveTextContent(status));
});

it("reports failed review loads rather than implying there are no records", async () => {
  vi.mocked(getRecommendations).mockRejectedValue(new Error("Review service unavailable"));
  render(<MonitoringWorkspace />);
  fireEvent.click(screen.getByRole("button", { name: "Reviews" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Review service unavailable");
  expect(screen.queryByText("No review records")).not.toBeInTheDocument();
});

it("keeps the stored status when a transition fails", async () => {
  vi.mocked(decideRecommendation).mockRejectedValue(new Error("Update unavailable"));
  await openReviews();
  fireEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Update unavailable");
  expect(screen.getByLabelText("Review status")).not.toHaveTextContent("reviewed");
});
