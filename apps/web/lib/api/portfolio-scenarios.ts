import { request } from "@/lib/api/client";

export type ScenarioRunExtra = {
  id: string;
  created_at: string;
  scenario_type?: string | null;
  shocks: { instruments: Record<string, number>; sectors: Record<string, number>; factors: Record<string, number> };
  volatility_before?: number | null;
  volatility_after?: number | null;
  volatility_change?: number | null;
  volatility_unavailable_reason?: string | null;
};
export type ScenarioRunExtras = { portfolio_id: string; volatility_method: string; runs: ScenarioRunExtra[] };

// Added after the first deployment: callers must tolerate a 404 from older API builds.
export function getScenarioRunExtras(portfolioId: string) {
  return request<ScenarioRunExtras>(`/portfolios/${encodeURIComponent(portfolioId)}/scenario-run-extras`);
}
