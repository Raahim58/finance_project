"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  LLMKey,
  Preferences,
  createLLMKey,
  getLLMKeys,
  getPreferences,
  updatePreferences
} from "@/lib/api";

export default function SettingsPage() {
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [keys, setKeys] = useState<LLMKey[]>([]);
  const [provider, setProvider] = useState("mock");
  const [apiKey, setApiKey] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void Promise.all([getPreferences(), getLLMKeys()])
      .then(([prefs, llmKeys]) => {
        setPreferences(prefs);
        setKeys(llmKeys);
      })
      .catch((error: Error) => setMessage(error.message));
  }, []);

  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preferences) return;
    const updated = await updatePreferences(preferences);
    setPreferences(updated);
    setMessage("Preferences saved.");
  }

  async function saveKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const created = await createLLMKey(provider, apiKey);
    setKeys([created, ...keys]);
    setApiKey("");
    setMessage("LLM key saved. The decrypted key was not returned to the browser.");
  }

  return (
    <section className="mx-auto grid max-w-5xl gap-6 px-5 py-8">
      <div>
        <h1 className="text-2xl font-semibold text-ink">Settings</h1>
        <p className="mt-2 text-sm text-muted">Manage preferences and encrypted BYOK LLM access.</p>
      </div>
      {message ? <p className="rounded-md border border-line bg-white px-4 py-3 text-sm text-ink">{message}</p> : null}
      <div className="grid gap-6 lg:grid-cols-2">
        <form onSubmit={savePreferences} className="grid gap-4 rounded-lg border border-line bg-white p-5">
          <h2 className="text-base font-semibold text-ink">Preferences</h2>
          <label className="grid gap-2 text-sm text-ink">
            Risk tolerance
            <select
              className="rounded-md border border-line px-3 py-2"
              value={preferences?.risk_tolerance ?? "balanced"}
              onChange={(event) =>
                setPreferences((current) => current && { ...current, risk_tolerance: event.target.value })
              }
            >
              <option value="conservative">Conservative</option>
              <option value="balanced">Balanced</option>
              <option value="aggressive">Aggressive</option>
            </select>
          </label>
          <label className="grid gap-2 text-sm text-ink">
            Investment horizon
            <select
              className="rounded-md border border-line px-3 py-2"
              value={preferences?.investment_horizon ?? "long-term"}
              onChange={(event) =>
                setPreferences((current) => current && { ...current, investment_horizon: event.target.value })
              }
            >
              <option value="short-term">Short-term</option>
              <option value="medium-term">Medium-term</option>
              <option value="long-term">Long-term</option>
            </select>
          </label>
          <label className="grid gap-2 text-sm text-ink">
            Analysis mode
            <select
              className="rounded-md border border-line px-3 py-2"
              value={preferences?.preferred_analysis_mode ?? "combined"}
              onChange={(event) =>
                setPreferences((current) => current && { ...current, preferred_analysis_mode: event.target.value })
              }
            >
              <option value="statistical">Statistical</option>
              <option value="policy/government">Policy/government</option>
              <option value="geopolitical">Geopolitical</option>
              <option value="fundamentals">Fundamentals</option>
              <option value="technical/market trend">Technical/market trend</option>
              <option value="combined">Combined</option>
            </select>
          </label>
          <button className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white" type="submit">
            Save preferences
          </button>
        </form>
        <form onSubmit={saveKey} className="grid content-start gap-4 rounded-lg border border-line bg-white p-5">
          <h2 className="text-base font-semibold text-ink">LLM API keys</h2>
          <label className="grid gap-2 text-sm text-ink">
            Provider
            <select className="rounded-md border border-line px-3 py-2" value={provider} onChange={(event) => setProvider(event.target.value)}>
              <option value="mock">Mock</option>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
              <option value="gemini">Gemini</option>
              <option value="openrouter">OpenRouter</option>
            </select>
          </label>
          <label className="grid gap-2 text-sm text-ink">
            API key
            <input
              className="rounded-md border border-line px-3 py-2"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="mock-secret-1234"
              required
            />
          </label>
          <button className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white" type="submit">
            Save key
          </button>
          <div className="grid gap-2">
            {keys.map((key) => (
              <div key={key.id} className="rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink">
                {key.provider}: {key.masked_api_key}
              </div>
            ))}
          </div>
        </form>
      </div>
    </section>
  );
}
