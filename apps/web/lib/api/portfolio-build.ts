import { request } from "./client";

export type BuildInstrument = { symbol: string; name: string | null; sector: string | null; official_website: string | null };
export type BuildExtras = {
  portfolio_id: string;
  instruments: BuildInstrument[];
  sector_weights: { current: Record<string, number>; proposed: Record<string, number> | null };
  max_drawdown: {
    current: number | null; proposed: number | null; basis: string; note: string | null;
    sample: { start: string; end: string; observations: number } | null;
  };
};

// Sector weights and drawdown are computed server-side from stored holdings and aligned prices.
export function getBuildExtras(portfolioId: string, targetWeights: Record<string, number> | null) {
  return request<BuildExtras>(`/portfolios/${encodeURIComponent(portfolioId)}/build-extras`, {
    method: "POST", body: JSON.stringify({ target_weights: targetWeights }),
  });
}
