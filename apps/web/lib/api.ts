import { API_BASE_URL, IMMUTABLE_CACHE_TTL_MS, getToken, request } from "@/lib/api/client";
export { clearApiCache, clearToken, getToken, setToken } from "@/lib/api/client";
export * from "@/lib/api/market";

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


export type FactProvenance = {source_name:string|null;document_type:string|null;is_synthetic:boolean;ingested_at:string|null};
export type CompanyEventSource = {source_name:string;source_url:string;published_at?:string|null;selection_status?:string|null};
export type CompanyEvent = {id:string;title:string;event_type:string;occurred_at:string;direction?:string|null;confidence?:string|number|null;sources:CompanyEventSource[]};
export type ResearchEvent = CompanyEvent & {materiality?:string|null;details?:Record<string,unknown>};
export type CompanyResearch = {
  instrument: { id:string; symbol:string; name:string; sector?:string|null };
  market: Record<string,unknown>|null;
  market_research: Record<string,unknown>;
  fundamentals: Array<{taxonomy_key:string;period_type:string;period_end:string;filing_date?:string|null;value:string|number;unit:string;currency?:string|null;document_id?:string|null;page_number?:number|null;provenance:FactProvenance}>;
  derived_fundamentals: { latest?:Record<string,Record<string,unknown>>; growth?:Record<string,Record<string,unknown>>; ratios?:Record<string,Record<string,unknown>>; valuation?:Record<string,unknown> };
  documents: Array<Record<string,unknown>>; events: CompanyEvent[]; portfolio_relevance:Array<Record<string,unknown>>;
  has_synthetic_data: boolean;
  context_contract_version:string;
  context:Record<string,unknown>;
  context_receipt:Record<string,unknown>;
  context_receipt_id:string;
  refresh_request_id?:string|null;
};

export type CandidateEvaluation = {
  candidate:{symbol:string;action:string;sizing:string;current_weight:number;proposed_weight:number};
  comparison:PortfolioComparison;
  stress:{current:Array<Record<string,unknown>>;proposed:Array<Record<string,unknown>>};
  optimizer:Record<string,unknown>|null;
  decision_explanation:{improved:Array<Record<string,unknown>>;deteriorated:Array<Record<string,unknown>>;sizing:string;assumptions:Record<string,unknown>;main_downside_scenarios:Array<Record<string,unknown>>};
  ledger_mutated:false;
  warnings:string[];
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
  source_tier: number;
  data_status: string;
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
  document_type: string;
  chunk_index: number;
  chunk_text: string;
  token_count: number;
  score: number;
  semantic_score: number;
  lexical_score: number;
  rrf_score: number;
  source_url?: string | null;
  page_number?: number | null;
  section_title?: string | null;
  metadata: Record<string, unknown>;
  citation: RagCitation;
  citation_eligible: boolean;
};

export type RagSearchResponse = {
  status: "ok" | "insufficient_evidence" | "needs_disambiguation";
  chunks: RagChunk[];
  citations: RagCitation[];
  scores: number[];
  audit: {
    plan: Record<string, unknown>;
    semantic_candidates: number;
    lexical_candidates: number;
    fused_candidates: number;
    admitted_candidates: number;
    rejected_by_reason: Record<string, number>;
    embedding_model: string;
    rrf_k: number;
  };
  disambiguation?: { symbols: string[]; reason: string } | null;
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
export type ComparisonMetric = Omit<OpenApi["schemas"]["ComparisonMetric"],"unit"|"classification"> & {unit:"decimal"|"percentage_point"|"ratio"|"PKR"|"days"|"count";classification?:"IMPROVED"|"WORSENED"|"UNCHANGED"|"REFERENCE"|"NOT_EVALUATED"};
export type PortfolioComparison = Omit<OpenApi["schemas"]["PortfolioComparisonResponse"],"metrics"|"current_compliance"|"proposed_compliance"|"trade_offs"> & {
  metrics:ComparisonMetric[];
  current_compliance:Compliance;
  proposed_compliance:Compliance;
  trade_offs:Array<{metric:string;label:string;direction:"IMPROVED"|"WORSENED"|"UNCHANGED"|"NOT_EVALUATED";delta:number|null;unit:"decimal"|"percentage_point"|"ratio"|"PKR"|"days"|"count"}>;
};
export type RiskBudget = Omit<OpenApi["schemas"]["RiskBudgetResponse"],"items"> & {portfolio_basis:"total_capital";items:Array<{symbol:string;total_capital_weight:number;risky_sleeve_weight?:number|null;component_risk:number;percentage_risk:number;target_risk?:number|null;residual?:number|null}>};
export type OptimizerResult = OpenApi["schemas"]["OptimizerResponse"];
export type Compliance = {compliant:boolean;status:"PASS"|"BREACH"|"NOT_EVALUATED";checks:Array<Record<string,unknown>>;violations:Array<Record<string,unknown>>;not_evaluated:Array<Record<string,unknown>>};
export type ScenarioResult = Omit<OpenApi["schemas"]["ScenarioResponse"],"positions"|"sector_contributions"|"compliance"> & {
  positions:Array<Record<string,unknown>>;
  sector_contributions:Record<string,number>;
  compliance:Compliance;
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
  synthesis: {execution_id?:string;mode:"llm_tool_loop"|"synthesis_unavailable"|"llm_grounded"|"deterministic_fallback"|"recommendation_synthesis_unavailable";provider?:string|null;model?:string|null;reason?:string|null;recommendation?:"Buy/Add"|"Hold"|"Reduce"|"Avoid"|"Insufficient Evidence"|null;confidence?:"High"|"Medium"|"Low"|null;horizon?:{label:string;source:"ips"|"user"|"not_available"}|null;instrument_ids?:string[];evidence_ids?:string[];context_receipt_ids?:string[];diagnostic_ids?:string[];repaired?:boolean;mode_scope?:"targeted"|"market_wide";web_grounding?:{status:"used"|"available_not_used"|"unsupported"|"disabled";tool_steps:number;citation_count:number};token_usage?:{input_tokens:number;output_tokens:number;cache_read_tokens?:number;cache_write_tokens?:number;reasoning_tokens?:number;transmitted_input_bytes?:number;total_tokens:number;model_calls:number;reported_by_provider:boolean}};
  context_contract_version?:string|null;
  context_status?:string|null;
  context_receipt?:Record<string,unknown>|null;
  refresh_request_id?:string|null;
  created_at: string;
};

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

export function startSampleSession() {
  return request<AuthResponse>("/auth/sample-session", { method: "POST" });
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
  return request<AllocationSet[]>(`/portfolios/${encodeURIComponent(portfolioId)}/allocations`, {}, IMMUTABLE_CACHE_TTL_MS);
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
  date_from?: string;
  date_to?: string;
  time_horizon?: "week"|"month"|"quarter"|"six_months"|"year"|"all";
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

export function getCapitalMarketAssumptions(portfolioId: string) { return request<CapitalMarketAssumptions>(`/portfolios/${encodeURIComponent(portfolioId)}/assumptions`, {}, IMMUTABLE_CACHE_TTL_MS); }
export function getEfficientFrontier(portfolioId: string) { return request<EfficientFrontier>(`/portfolios/${encodeURIComponent(portfolioId)}/frontier`); }
export function getCapmSml(portfolioId: string) { return request<CapmSml>(`/portfolios/${encodeURIComponent(portfolioId)}/capm-sml`); }
export function getRollingRisk(portfolioId: string, window = 60) { return request<RollingRisk>(`/portfolios/${encodeURIComponent(portfolioId)}/rolling-risk?window=${window}`); }
export function getReturnDistribution(portfolioId: string) { return request<ReturnDistribution>(`/portfolios/${encodeURIComponent(portfolioId)}/return-distribution`); }
export function comparePortfolio(portfolioId: string, targetWeights: Record<string,number>, label = "Proposed portfolio") { return request<PortfolioComparison>(`/portfolios/${encodeURIComponent(portfolioId)}/comparison`, { method: "POST", body: JSON.stringify({ target_weights: targetWeights, label }) }); }
export function getRiskBudget(portfolioId: string) { return request<RiskBudget>(`/portfolios/${encodeURIComponent(portfolioId)}/risk-budget`); }
export function runOptimizer(portfolioId: string, payload: Record<string,unknown>) { return request<OptimizerResult>(`/portfolios/${encodeURIComponent(portfolioId)}/optimizer-runs`, { method: "POST", body: JSON.stringify(payload) }); }
export function getOptimizerRuns(portfolioId: string) { return request<Array<Record<string,unknown>>>(`/portfolios/${encodeURIComponent(portfolioId)}/optimizer-runs`); }

export function getIpsCompliance(portfolioId: string) {
  return request<Compliance>(`/portfolios/${encodeURIComponent(portfolioId)}/ips/compliance`);
}

export function createIpsVersion(portfolioId: string, payload: Record<string, unknown>, confirm = false) {
  return request<Record<string, unknown>>(`/portfolios/${encodeURIComponent(portfolioId)}/ips/${confirm ? "confirm" : "draft"}`, { method: "POST", body: JSON.stringify(payload) });
}

export function getIpsVersions(portfolioId: string) { return request<IpsVersion[]>(`/portfolios/${encodeURIComponent(portfolioId)}/ips/versions`, {}, IMMUTABLE_CACHE_TTL_MS); }

export function createAllocation(portfolioId: string, payload: Record<string, unknown>) {
  return request<Record<string, unknown>>(`/portfolios/${encodeURIComponent(portfolioId)}/allocations`, { method: "POST", body: JSON.stringify(payload) });
}

export function runScenario(portfolioId: string, payload: Record<string, unknown>) {
  return request<ScenarioResult>(`/portfolios/${encodeURIComponent(portfolioId)}/scenario-runs`, { method: "POST", body: JSON.stringify(payload) });
}

export function getScenarioRuns(portfolioId: string) { return request<ScenarioResult[]>(`/portfolios/${encodeURIComponent(portfolioId)}/scenario-runs`); }
export type ScenarioTemplate={id:string;name:string;description:string;version:string;sector_shocks:Record<string,number>;factor_shocks:Record<string,number>;fallback_security_shock?:number;required_mappings:string[]};
export function getScenarioTemplates(){return request<ScenarioTemplate[]>("/scenario-templates");}
export type MacroRegime={regime:string;method:string;method_note:string;dimensions:Record<string,Record<string,unknown>>;stress_signals:string[];suggested_scenario_ids:string[];portfolio_relevance?:Record<string,unknown>|null};
export function getMacroRegime(portfolioId?:string){return request<MacroRegime>(`/macro/regime${portfolioId?`?portfolio_id=${encodeURIComponent(portfolioId)}`:""}`);}
export function runHistoricalReplay(portfolioId:string,startDate:string,endDate:string,useCurrentHoldings=true){return request<HistoricalReplay>(`/portfolios/${encodeURIComponent(portfolioId)}/scenarios/historical-replay`,{method:"POST",body:JSON.stringify({start_date:startDate,end_date:endDate,use_current_holdings:useCurrentHoldings})});}

export type AssistantRun = {execution_id:string;status:string;error_code?:string;error_detail?:string|null;response?:AssistantResult|null};
const ACTIVE_ASSISTANT_RUN = "assistant.activeExecution";
const PENDING_ASSISTANT_REQUEST = "assistant.pendingRequest";
export function activeAssistantExecution(){return sessionStorage.getItem(ACTIVE_ASSISTANT_RUN)??(sessionStorage.getItem(PENDING_ASSISTANT_REQUEST)?"pending":null);}
export async function resumeAssistantExecution(executionId:string):Promise<AssistantResult>{
  if(executionId==="pending"){
    const body=sessionStorage.getItem(PENDING_ASSISTANT_REQUEST);
    if(!body)throw new Error("Pending assistant request is unavailable");
    const run=await request<AssistantRun>("/assistant/runs",{method:"POST",body});
    executionId=run.execution_id;
    sessionStorage.setItem(ACTIVE_ASSISTANT_RUN,executionId);
    sessionStorage.removeItem(PENDING_ASSISTANT_REQUEST);
  }
  for (;;) {
    const run=await request<AssistantRun>(`/assistant/runs/${encodeURIComponent(executionId)}`);
    if(run.response){
      if(sessionStorage.getItem(ACTIVE_ASSISTANT_RUN)===executionId) sessionStorage.removeItem(ACTIVE_ASSISTANT_RUN);
      return run.response;
    }
    if(run.status==="failed"){
      if(sessionStorage.getItem(ACTIVE_ASSISTANT_RUN)===executionId) sessionStorage.removeItem(ACTIVE_ASSISTANT_RUN);
      throw new Error(run.error_detail||`Assistant execution failed (${run.error_code??"unknown"}).`);
    }
    await new Promise(resolve=>setTimeout(resolve,1000));
  }
}
export function acknowledgeAssistantExecution(executionId:string){
  return request<void>(`/assistant/runs/${encodeURIComponent(executionId)}/receipt`,{method:"POST"});
}
export async function sendAssistantMessage(question: string, portfolioId?: string, instrumentId?: string) {
  sessionStorage.setItem(PENDING_ASSISTANT_REQUEST,JSON.stringify({client_request_id:crypto.randomUUID(),question, portfolio_id: portfolioId || null, instrument_id: instrumentId || null}));
  return resumeAssistantExecution("pending");
}

export type AlertStatus = "active" | "acknowledged" | "resolved" | "all";
export function getAlerts(portfolioId?: string, status: AlertStatus = "active") {
  const params = new URLSearchParams({ status });
  if (portfolioId) params.set("portfolio_id", portfolioId);
  return request<Array<Record<string, unknown>>>(`/monitoring/alerts?${params.toString()}`);
}

export function getRecommendations() {
  return request<Array<Record<string, unknown>>>("/recommendations");
}

export function decideRecommendation(recommendationId: string, decision: "accepted" | "reviewed" | "dismissed" | "rejected" | "superseded" | "resolved") {
  return request<{ id: string; status: string }>(`/recommendations/${encodeURIComponent(recommendationId)}?decision=${decision}`, { method: "PATCH" });
}

export function acknowledgeAlert(alertId: string, note?: string) {
  return request<Record<string, unknown>>(`/monitoring/alerts/${encodeURIComponent(alertId)}/acknowledge`, { method: "POST", body: JSON.stringify({ note: note || null }) });
}

export type AuditEvent = {
  id: string; user_id: string; portfolio_id?: string | null; event_type: string; entity_type: string; entity_id: string;
  entity_version?: number | null; previous_state: Record<string, unknown>; new_state: Record<string, unknown>;
  data_cutoff?: string | null; source?: string | null; note?: string | null; created_at: string;
};
export function getAuditEvents(portfolioId?: string) {
  return request<AuditEvent[]>(`/audit-events${portfolioId ? `?portfolio_id=${encodeURIComponent(portfolioId)}` : ""}`);
}

export function saveFinancialProfile(data: Record<string, unknown>, confirm = true) {
  return request<Record<string, unknown>>(`/profiles/financial/${confirm ? "confirm" : "draft"}`, { method: "POST", body: JSON.stringify({ data }) });
}

export function searchInstruments(query = "") {
  return request<Array<{ id: string; symbol: string; name: string; sector?: string | null }>>(`/instruments?query=${encodeURIComponent(query)}`);
}

export async function getCompanyResearch(symbol:string,options?:{portfolioId?:string;researchPurpose?:"recent_changes"|"outlook"|"risks"|"drivers";question?:string}){const matches=await searchInstruments(symbol);const instrument=matches.find(item=>item.symbol.toUpperCase()===symbol.toUpperCase());if(!instrument)throw new Error("Instrument not found");const params=new URLSearchParams();if(options?.portfolioId)params.set("portfolio_id",options.portfolioId);if(options?.researchPurpose)params.set("research_purpose",options.researchPurpose);if(options?.question)params.set("question",options.question);const query=params.size?`?${params.toString()}`:"";return request<CompanyResearch>(`/companies/${encodeURIComponent(instrument.id)}/overview${query}`);}
export function getContextRefresh(refreshId:string){return request<{refresh_request_id:string;status:string;needs_rebuild?:boolean;result?:CompanyResearch}>(`/research/context-refreshes/${encodeURIComponent(refreshId)}`);}
export function deactivateContextRefresh(refreshId:string){return request<{refresh_request_id:string;active:boolean}>(`/research/context-refreshes/${encodeURIComponent(refreshId)}/deactivate`,{method:"POST"});}
export function getResearchEvents(eventType?:string,limit=30){const params=new URLSearchParams({limit:String(limit)});if(eventType)params.set("event_type",eventType);return request<ResearchEvent[]>(`/research/events?${params.toString()}`);}
export function evaluateSecurity(symbol:string,payload:Record<string,unknown>){return request<CandidateEvaluation>(`/intelligence/securities/${encodeURIComponent(symbol)}/evaluate`,{method:"POST",body:JSON.stringify(payload)});}
export function saveSecurityProposal(symbol:string,payload:Record<string,unknown>){return request<{proposal:AllocationSet;evaluation:CandidateEvaluation;ledger_mutated:false}>(`/intelligence/securities/${encodeURIComponent(symbol)}/proposals`,{method:"POST",body:JSON.stringify(payload)});}
import type { components as OpenApi } from "@/lib/generated/api";
