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
