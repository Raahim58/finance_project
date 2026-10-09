export type ProviderOption = { id: string; label: string; mark: string; models: string[] };

/** Provider ids must match the API provider registry; models are suggestions, any saved model id is preserved. */
export const PROVIDERS: ProviderOption[] = [
  { id: "zai", label: "Z.ai", mark: "Z", models: ["glm-4.7-flash", "glm-4.5-flash"] },
  { id: "anthropic", label: "Anthropic", mark: "A", models: ["claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5"] },
  { id: "openai", label: "OpenAI", mark: "O", models: ["gpt-4.1-mini", "gpt-4.1"] },
  { id: "gemini", label: "Gemini", mark: "G", models: ["gemini-2.5-flash", "gemini-2.5-pro"] },
  { id: "openrouter", label: "OpenRouter", mark: "R", models: ["openai/gpt-4.1-mini"] },
];

export const ANALYSIS_LENSES = ["combined", "statistical", "policy/government", "geopolitical", "fundamentals", "technical/market trend"];
export const CADENCES: Array<[string, string]> = [["frequently", "Frequent"], ["normally", "Daily"], ["minimally", "Minimal"]];
/** Topic key, title, description, and the monitoring alert_type values that belong to it. */
export const NOTIFICATION_TOPICS: Array<[string, string, string, string[]]> = [
  ["mandate_breaches", "Mandate and risk limits", "A position, drawdown, volatility, VaR, liquidity or beta limit is breached.", ["position_weight", "concentration", "drawdown", "volatility", "var", "liquidity", "beta_shift"]],
  ["data_freshness", "Data freshness", "Market data goes stale or an ingestion run fails.", ["stale_data", "ingestion_failure"]],
  ["research_updates", "Research events", "A new event is detected for a company you hold.", ["event"]],
];

export function topicEnabled(prefs: Record<string, boolean> | undefined, alertType: string) {
  const topic = NOTIFICATION_TOPICS.find(([, , , types]) => types.includes(alertType));
  return topic ? (prefs?.[topic[0]] ?? true) : true;
}

export function modelOptions(provider: ProviderOption, saved?: string | null) {
  return saved && !provider.models.includes(saved) ? [saved, ...provider.models] : provider.models;
}
