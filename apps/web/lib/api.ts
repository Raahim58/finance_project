export type AuthResponse = {
  access_token: string;
  token_type: string;
};

export type Preferences = {
  default_llm_provider: string;
  risk_tolerance: string;
  investment_horizon: string;
  preferred_analysis_mode: string;
  preferred_sectors: string[];
  avoided_sectors: string[];
  notification_preferences: Record<string, unknown>;
  followup_frequency: string;
};

export type LLMKey = {
  id: string;
  provider: string;
  masked_api_key: string;
  default_model?: string;
  is_active: boolean;
  last_used_at?: string;
};

export type Exchange = {
  code: string;
  name: string;
  timezone: string;
};

export type Company = {
  id: string;
  symbol: string;
  name: string;
  sector: string;
  exchange: Exchange;
  official_website?: string | null;
  psx_url?: string | null;
  description?: string | null;
  is_active: boolean;
};

export type MarketPrice = {
  symbol: string;
  trade_date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  previous_close: string;
  change: string;
  change_percent: string;
  volume: number;
  value: string;
  market_cap?: string | null;
  source: string;
  source_url?: string | null;
  ingested_at: string;
};

export type MarketSnapshot = {
  snapshot_date: string;
  index_name: string;
  index_value: string;
  index_change: string;
  index_change_percent: string;
  total_volume: number;
  total_value: string;
  source: string;
  ingested_at: string;
};

export type SectorDailyStats = {
  sector: string;
  trade_date: string;
  total_volume: number;
  total_value: string;
  average_change_percent: string;
  advancers: number;
  decliners: number;
  unchanged: number;
  source: string;
};

export type CompanyDetail = {
  company: Company;
  latest_price?: MarketPrice | null;
};

export type CompanyResearch = {
  instrument: { id:string; symbol:string; name:string; sector?:string|null };
  market: Record<string,unknown>|null;
  market_research: Record<string,unknown>;
  fundamentals: Array<{taxonomy_key:string;period_type:string;period_end:string;filing_date?:string|null;value:string|number;unit:string;currency?:string|null;document_id?:string|null;page_number?:number|null}>;
  derived_fundamentals: { latest?:Record<string,Record<string,unknown>>; growth?:Record<string,Record<string,unknown>>; ratios?:Record<string,Record<string,unknown>>; valuation?:Record<string,unknown> };
  documents: Array<Record<string,unknown>>; events: Array<Record<string,unknown>>; portfolio_relevance:Array<Record<string,unknown>>;
};

export type MarketOverview = {
  snapshot?: MarketSnapshot | null;
  top_gainers: MarketPrice[];
  top_losers: MarketPrice[];
  top_volume: MarketPrice[];
  sectors: SectorDailyStats[];
};

export type MarketFreshness = {
  market_data_mode: string;
  refresh_seconds: number;
  last_successful_ingestion_at?: string | null;
  latest_trade_date?: string | null;
  latest_source?: string | null;
  latest_attempted_provider?: string | null;
  latest_used_provider?: string | null;
  is_stale: boolean;
  stale_warning?: string | null;
  backup_warning?: string | null;
};

export type Portfolio = {
  id: string;
  name: string;
  base_currency: string;
  source_mode: string;
  provider_name: string;
  last_synced_at?: string | null;
  description?: string | null;
  goal_summary?: string | null;
  is_default: boolean;
  archived_at?: string | null;
  history_start?: string | null;
  history_complete: boolean;
  selected_ips_version_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type Holding = {
  id: string;
  portfolio_id: string;
  company_id: string;
  symbol: string;
  quantity: string;
  average_cost: string;
  created_at: string;
  updated_at: string;
};

export type HoldingSummary = {
  holding_id: string;
  symbol: string;
  name: string;
  sector: string;
  quantity: string;
  average_cost: string;
  latest_price?: string | null;
  latest_price_date?: string | null;
  cost_basis: string;
  market_value: string;
  unrealized_gain_loss: string;
  unrealized_gain_loss_percent?: string | null;
  day_change?: string | null;
  day_change_percent?: string | null;
  data_source?: string | null;
};

export type PortfolioSummary = {
  portfolio: Portfolio;
  total_value: string;
  cost_basis: string;
  unrealized_gain_loss: string;
  unrealized_gain_loss_percent?: string | null;
  day_change: string;
  day_change_percent?: string | null;
  cash_balance: string;
  holdings: HoldingSummary[];
  data_freshness_date?: string | null;
  data_source?: string | null;
  valuation_complete: boolean;
  unpriced_symbols: string[];
  valuation_note?: string | null;
};

export type PortfolioPerformancePoint = {
  value_date: string;
  total_value: string;
  external_cash_flow: string;
  value_change: string;
  day_change: string;
  day_change_percent?: string | null;
  cumulative_twr_percent?: string | null;
};

export type Transaction = {
  id: string; portfolio_id: string; symbol: string; transaction_type: string;
  quantity?: string | null; price?: string | null; amount: string; transaction_date: string;
  notes?: string | null; source: string; currency: string; fees: string; taxes: string;
  settlement_date?: string | null; created_at: string;
};

export type AllocationSet = {
  id: string; portfolio_id: string; kind: string; version: number; status: string;
  base_value?: string | null; assumptions: Record<string, unknown>; created_at: string;
  items: Array<{ id: string; symbol: string; target_weight: string; target_amount?: string | null; locked: boolean; is_cash: boolean }>;
};

export type SectorExposure = {
  sector: string;
  market_value: string;
  weight_percent: string;
};

export type CompanyExposure = {
  symbol: string;
  name: string;
  market_value: string;
  weight_percent: string;
};

export type PortfolioExposure = {
  total_value: string;
  by_sector: SectorExposure[];
  by_company: CompanyExposure[];
};

export type PortfolioRiskFlag = {
  severity: string;
  code: string;
  message: string;
  value?: string | null;
};

export type PortfolioRiskFlags = {
  flags: PortfolioRiskFlag[];
};

export type ApiDocument = {
  id: string;
  symbol?: string | null;
  sector?: string | null;
  document_type: string;
  title: string;
  fiscal_year?: number | null;
  quarter?: string | null;
  source_name: string;
  source_url?: string | null;
  local_file_path?: string | null;
  content_hash: string;
  published_date?: string | null;
  parsed_at?: string | null;
  status: string;
  error_message?: string | null;
  created_at: string;
};

export type RagCitation = {
  id: string;
  document_id: string;
  chunk_id?: string | null;
  source_name: string;
  source_url?: string | null;
  title: string;
  page_number?: number | null;
  quote_snippet?: string | null;
  created_at: string;
};

export type RagChunk = {
  id: string;
  document_id: string;
  symbol?: string | null;
  chunk_index: number;
  chunk_text: string;
  token_count: number;
  score: number;
  source_url?: string | null;
  page_number?: number | null;
  section_title?: string | null;
  metadata: Record<string, unknown>;
  citation: RagCitation;
};

export type RagSearchResponse = {
  chunks: RagChunk[];
  citations: RagCitation[];
  scores: number[];
};

export type PortfolioQuant = {
  data_cutoff: string;
  symbols: string[];
  sample_size: number;
  annualization: number;
  covariance_shrinkage: number;
  portfolio: Record<string, unknown>;
  benchmark: Record<string, unknown>;
  rolling: Record<string, unknown>;
  covariance: number[][];
  correlation: number[][];
  risk_contributions: Record<string, number>;
  warnings: string[];
  run_id?: string | null;
};

export type IpsVersion = OpenApi["schemas"]["IPSVersionResponse"];
export type CapitalMarketAssumptions = OpenApi["schemas"]["CapitalMarketAssumptionsResponse"];
export type FrontierPoint = OpenApi["schemas"]["FrontierPoint"];
export type EfficientFrontier = OpenApi["schemas"]["EfficientFrontierResponse"];
export type CapmSml = OpenApi["schemas"]["CapmSmlResponse"];
export type RollingRisk = OpenApi["schemas"]["RollingRiskResponse"];
export type ReturnDistribution = OpenApi["schemas"]["ReturnDistributionResponse"];
export type ComparisonMetric = OpenApi["schemas"]["ComparisonMetric"];
export type PortfolioComparison = Omit<OpenApi["schemas"]["PortfolioComparisonResponse"],"current_compliance"|"proposed_compliance"|"trade_offs"> & {
  current_compliance:{compliant:boolean;violations:Array<Record<string,unknown>>};
  proposed_compliance:{compliant:boolean;violations:Array<Record<string,unknown>>};
  trade_offs:Array<{metric:string;label:string;direction:string;delta:number}>;
};
export type RiskBudget = OpenApi["schemas"]["RiskBudgetResponse"];
export type OptimizerResult = OpenApi["schemas"]["OptimizerResponse"];
export type ScenarioResult = Omit<OpenApi["schemas"]["ScenarioResponse"],"positions"|"sector_contributions"|"compliance"> & {
  positions:Array<Record<string,unknown>>;
  sector_contributions:Record<string,number>;
  compliance:{compliant?:boolean;violations?:Array<Record<string,unknown>>};
};

export type HistoricalReplay = { portfolio_id:string; start_date:string; end_date:string; counterfactual:boolean; assumption:string; start_value:number; end_value:number; pnl:number; return?:number|null; path:Array<{date:string;value:number}>; max_drawdown?:number|null; recovery_days?:number|null; sector_pnl_contribution:Record<string,number>; positions:Array<Record<string,unknown>>; total_return_available:boolean; total_return_unavailable_reason:string };

export type AssistantResult = {
  conversation_id: string;
  message_id: string;
  answer: string;
  uncertainty: string[];
  calculated_evidence: Array<Record<string, unknown>>;
  source_citations: Array<Record<string, unknown>>;
  freshness_warnings: string[];
  tool_trace: Array<Record<string, unknown>>;
  created_at: string;
};

// Keep browser requests on the frontend origin. Next proxies /api to FastAPI,
// which also makes temporary HTTPS preview tunnels work without CORS or mixed content.
const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";
const TOKEN_KEY = "psx_ai_token";
const GET_CACHE_TTL_MS = 60_000;
type CachedResponse = { expiresAt: number; value: unknown };
const responseCache = new Map<string, CachedResponse>();
const pendingRequests = new Map<string, Promise<unknown>>();

export function clearApiCache() {
  responseCache.clear();
  pendingRequests.clear();
}

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  clearApiCache();
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  clearApiCache();
  window.localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const method = (options.method ?? "GET").toUpperCase();
  const cacheKey = `${token ? "authenticated" : "anonymous"}:${path}`;
  if (method === "GET") {
    const cached = responseCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) return cached.value as T;
    if (cached) responseCache.delete(cacheKey);
    const pending = pendingRequests.get(cacheKey);
    if (pending) return pending as Promise<T>;
  } else {
    // Mutations can affect summaries, analytics, compliance, and market values.
    clearApiCache();
  }
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const execute = async () => {
    const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = body.detail;
      const fallback = `Request failed: ${response.status} (${method} ${path})`;
      throw new Error(typeof detail === "string" ? `${detail} (${method} ${path})` : detail ? `${JSON.stringify(detail)} (${method} ${path})` : fallback);
    }
    if (response.status === 204) return undefined as T;
    const value = await response.json() as T;
    if (method === "GET") responseCache.set(cacheKey, { value, expiresAt: Date.now() + GET_CACHE_TTL_MS });
    return value;
  };
  const result = execute();
  if (method === "GET") pendingRequests.set(cacheKey, result);
  try {
    return await result;
  } finally {
    if (method === "GET") pendingRequests.delete(cacheKey);
  }
}

export function signup(email: string, password: string, fullName?: string) {
  return request<AuthResponse>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, full_name: fullName || null })
  });
}

export function login(email: string, password: string) {
  return request<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });
}

export function getPreferences() {
  return request<Preferences>("/settings/preferences");
}

export function updatePreferences(payload: Partial<Preferences>) {
  return request<Preferences>("/settings/preferences", {
    method: "PATCH",
    body: JSON.stringify(payload)
  });
}

export function getLLMKeys() {
  return request<LLMKey[]>("/settings/llm-keys");
}

export function createLLMKey(provider: string, apiKey: string, defaultModel?: string) {
  return request<LLMKey>("/settings/llm-keys", {
    method: "POST",
    body: JSON.stringify({ provider, api_key: apiKey, default_model: defaultModel || null })
  });
}

export function getMarketOverview() {
  return request<MarketOverview>("/market/overview");
}

export function getMarketFreshness() {
  return request<MarketFreshness>("/market/freshness");
}

export function getCompanies(query?: string) {
  const params = query ? `?q=${encodeURIComponent(query)}` : "";
  return request<Company[]>(`/market/companies${params}`);
}

export function getCompanyDetail(symbol: string) {
  return request<CompanyDetail>(`/market/company/${encodeURIComponent(symbol)}`);
}

export function getCompanyHistory(symbol: string, limit = 180) {
  return request<MarketPrice[]>(
    `/market/company/${encodeURIComponent(symbol)}/history?limit=${encodeURIComponent(String(limit))}`
  );
}

export function getPortfolios() {
  return request<Portfolio[]>("/portfolios");
}

export function createPortfolio(name: string, baseCurrency = "PKR") {
  return request<Portfolio>("/portfolios", {
    method: "POST",
    body: JSON.stringify({ name, base_currency: baseCurrency })
  });
}

export function duplicatePortfolio(portfolioId: string, name: string, includePositions = true) {
  return request<Portfolio>(`/portfolios/${encodeURIComponent(portfolioId)}/duplicate`, { method: "POST", body: JSON.stringify({ name, include_positions: includePositions }) });
}

export function archivePortfolio(portfolioId: string) {
  return request<Portfolio>(`/portfolios/${encodeURIComponent(portfolioId)}/archive`, { method: "POST" });
}

export function comparePortfolios(portfolioIds: string[]) {
  const query = portfolioIds.map((id) => `portfolio_ids=${encodeURIComponent(id)}`).join("&");
  return request<{ portfolios: PortfolioSummary[] }>(`/portfolios/compare?${query}`);
}

export function getPortfolioSummary(portfolioId: string) {
  return request<PortfolioSummary>(`/portfolios/${encodeURIComponent(portfolioId)}/summary`);
}

export function getPortfolioExposure(portfolioId: string) {
  return request<PortfolioExposure>(`/portfolios/${encodeURIComponent(portfolioId)}/exposure`);
}

export function getPortfolioRiskFlags(portfolioId: string) {
  return request<PortfolioRiskFlags>(`/portfolios/${encodeURIComponent(portfolioId)}/risk-flags`);
}

export function getPortfolioPerformance(portfolioId: string, limit = 90) {
  return request<PortfolioPerformancePoint[]>(`/portfolios/${encodeURIComponent(portfolioId)}/performance?limit=${limit}`);
}

export function getTransactions(portfolioId: string) {
  return request<Transaction[]>(`/portfolios/${encodeURIComponent(portfolioId)}/transactions`);
}

export function getAllocations(portfolioId: string) {
  return request<AllocationSet[]>(`/portfolios/${encodeURIComponent(portfolioId)}/allocations`);
}

export function addHolding(portfolioId: string, symbol: string, quantity: string, averageCost: string) {
  return request<Holding>(`/portfolios/${encodeURIComponent(portfolioId)}/holdings`, {
    method: "POST",
    body: JSON.stringify({
      symbol,
      quantity,
      average_cost: averageCost
    })
  });
}

export function getDocuments(symbol?: string) {
  const params = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
  return request<ApiDocument[]>(`/documents${params}`);
}

export function uploadDocument(formData: FormData) {
  const token = getToken();
  const headers = new Headers();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_BASE_URL}/documents/upload`, {
    method: "POST",
    headers,
    body: formData
  }).then(async (response) => {
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail ?? `Request failed: ${response.status}`);
    }
    return response.json() as Promise<ApiDocument>;
  });
}

export function searchRag(payload: {
  query: string;
  symbols?: string[];
  sectors?: string[];
  document_types?: string[];
  portfolio_id?: string;
  limit?: number;
}) {
  return request<RagSearchResponse>("/rag/search", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getPortfolioQuant(portfolioId: string) {
  return request<PortfolioQuant>(`/portfolios/${encodeURIComponent(portfolioId)}/quant`);
}

export function getCapitalMarketAssumptions(portfolioId: string) { return request<CapitalMarketAssumptions>(`/portfolios/${encodeURIComponent(portfolioId)}/assumptions`); }
export function getEfficientFrontier(portfolioId: string) { return request<EfficientFrontier>(`/portfolios/${encodeURIComponent(portfolioId)}/frontier`); }
export function getCapmSml(portfolioId: string) { return request<CapmSml>(`/portfolios/${encodeURIComponent(portfolioId)}/capm-sml`); }
export function getRollingRisk(portfolioId: string, window = 60) { return request<RollingRisk>(`/portfolios/${encodeURIComponent(portfolioId)}/rolling-risk?window=${window}`); }
export function getReturnDistribution(portfolioId: string) { return request<ReturnDistribution>(`/portfolios/${encodeURIComponent(portfolioId)}/return-distribution`); }
export function comparePortfolio(portfolioId: string, targetWeights: Record<string,number>, label = "Proposed portfolio") { return request<PortfolioComparison>(`/portfolios/${encodeURIComponent(portfolioId)}/comparison`, { method: "POST", body: JSON.stringify({ target_weights: targetWeights, label }) }); }
export function getRiskBudget(portfolioId: string) { return request<RiskBudget>(`/portfolios/${encodeURIComponent(portfolioId)}/risk-budget`); }
export function runOptimizer(portfolioId: string, payload: Record<string,unknown>) { return request<OptimizerResult>(`/portfolios/${encodeURIComponent(portfolioId)}/optimizer-runs`, { method: "POST", body: JSON.stringify(payload) }); }
export function getOptimizerRuns(portfolioId: string) { return request<Array<Record<string,unknown>>>(`/portfolios/${encodeURIComponent(portfolioId)}/optimizer-runs`); }

export function getIpsCompliance(portfolioId: string) {
  return request<{ compliant: boolean; violations: Array<Record<string, unknown>> }>(`/portfolios/${encodeURIComponent(portfolioId)}/ips/compliance`);
}

export function createIpsVersion(portfolioId: string, payload: Record<string, unknown>, confirm = false) {
  return request<Record<string, unknown>>(`/portfolios/${encodeURIComponent(portfolioId)}/ips/${confirm ? "confirm" : "draft"}`, { method: "POST", body: JSON.stringify(payload) });
}

export function getIpsVersions(portfolioId: string) { return request<IpsVersion[]>(`/portfolios/${encodeURIComponent(portfolioId)}/ips/versions`); }

export function createAllocation(portfolioId: string, payload: Record<string, unknown>) {
  return request<Record<string, unknown>>(`/portfolios/${encodeURIComponent(portfolioId)}/allocations`, { method: "POST", body: JSON.stringify(payload) });
}

export function runScenario(portfolioId: string, payload: Record<string, unknown>) {
  return request<ScenarioResult>(`/portfolios/${encodeURIComponent(portfolioId)}/scenario-runs`, { method: "POST", body: JSON.stringify(payload) });
}

export function getScenarioRuns(portfolioId: string) { return request<ScenarioResult[]>(`/portfolios/${encodeURIComponent(portfolioId)}/scenario-runs`); }
export function runHistoricalReplay(portfolioId:string,startDate:string,endDate:string,useCurrentHoldings=true){return request<HistoricalReplay>(`/portfolios/${encodeURIComponent(portfolioId)}/scenarios/historical-replay`,{method:"POST",body:JSON.stringify({start_date:startDate,end_date:endDate,use_current_holdings:useCurrentHoldings})});}

export function sendAssistantMessage(question: string, portfolioId?: string) {
  return request<AssistantResult>("/assistant/messages", { method: "POST", body: JSON.stringify({ question, portfolio_id: portfolioId || null }) });
}

export function getAlerts(portfolioId?: string) {
  return request<Array<Record<string, unknown>>>(`/monitoring/alerts${portfolioId ? `?portfolio_id=${encodeURIComponent(portfolioId)}` : ""}`);
}

export function getRecommendations() {
  return request<Array<Record<string, unknown>>>("/recommendations");
}

export function decideRecommendation(recommendationId: string, decision: "accepted" | "reviewed" | "dismissed") {
  return request<{ id: string; status: string }>(`/recommendations/${encodeURIComponent(recommendationId)}?decision=${decision}`, { method: "PATCH" });
}

export function acknowledgeAlert(alertId: string) {
  return request<Record<string, unknown>>(`/monitoring/alerts/${encodeURIComponent(alertId)}/acknowledge`, { method: "POST" });
}

export function saveFinancialProfile(data: Record<string, unknown>, confirm = true) {
  return request<Record<string, unknown>>(`/profiles/financial/${confirm ? "confirm" : "draft"}`, { method: "POST", body: JSON.stringify({ data }) });
}

export function searchInstruments(query = "") {
  return request<Array<{ id: string; symbol: string; name: string; sector?: string | null }>>(`/instruments?query=${encodeURIComponent(query)}`);
}

export async function getCompanyResearch(symbol:string){const matches=await searchInstruments(symbol);const instrument=matches.find(item=>item.symbol.toUpperCase()===symbol.toUpperCase());if(!instrument)throw new Error("Instrument not found");return request<CompanyResearch>(`/companies/${encodeURIComponent(instrument.id)}/overview`);}
import type { components as OpenApi } from "@/lib/generated/api";
