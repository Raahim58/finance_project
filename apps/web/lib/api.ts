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

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const TOKEN_KEY = "psx_ai_token";

export function getToken() {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
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

export function getPortfolioSummary(portfolioId: string) {
  return request<PortfolioSummary>(`/portfolios/${encodeURIComponent(portfolioId)}/summary`);
}

export function getPortfolioExposure(portfolioId: string) {
  return request<PortfolioExposure>(`/portfolios/${encodeURIComponent(portfolioId)}/exposure`);
}

export function getPortfolioRiskFlags(portfolioId: string) {
  return request<PortfolioRiskFlags>(`/portfolios/${encodeURIComponent(portfolioId)}/risk-flags`);
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
  limit?: number;
}) {
  return request<RagSearchResponse>("/rag/search", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}
