"use client";

import { useEffect, useRef, useState } from "react";
import { getLLMKeys, getPreferences, updatePreferences, type LLMKey } from "@/lib/api";

const labels: Record<string, string> = {
  anthropic: "Anthropic", zai: "Z.ai", gemini: "Google Gemini",
  openai: "OpenAI", openrouter: "OpenRouter", mock: "Demo model",
};

export function AssistantProviderSwitch({ onProviderChange, onSavingChange }: {
  onProviderChange: (provider: string | null) => void;
  onSavingChange: (saving: boolean) => void;
}) {
  const [providers, setProviders] = useState<LLMKey[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    let current = true;
    void Promise.all([getPreferences(), getLLMKeys()]).then(([prefs, keys]) => {
      if (!current) return;
      // The key endpoint is newest-first; use the same newest active model as the server.
      const available = keys.filter((key, index, all) => key.is_active &&
        all.findIndex((other) => other.is_active && other.provider === key.provider) === index);
      setProviders(available);
      setSelected(prefs.default_llm_provider);
      onProviderChange(prefs.default_llm_provider);
    }).catch((e: Error) => { if (current) setError(e.message); });
    return () => { current = false; mounted.current = false; };
  }, [onProviderChange]);

  async function switchProvider(provider: string) {
    if (saving || provider === selected) return;
    setSaving(true);
    onSavingChange(true);
    setError(null);
    try {
      const prefs = await updatePreferences({ default_llm_provider: provider });
      if (!mounted.current) return;
      setSelected(prefs.default_llm_provider);
      onProviderChange(prefs.default_llm_provider);
      setOpened(false);
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setSaving(false);
      onSavingChange(false);
    }
  }

  const model = providers.find((key) => key.provider === selected)?.default_model;
  return <div className="assistant-provider">
    <button type="button" className="assistant-provider-trigger" aria-label="Switch AI provider" aria-expanded={opened}
      disabled={saving} onClick={() => setOpened(!opened)}>
      <span>{saving ? "Switching…" : selected ? (labels[selected] ?? selected) : "Provider"}</span>
      {model ? <span className="assistant-provider-model">{model}</span> : null}
      <span aria-hidden="true">⌄</span>
    </button>
    {opened ? <div className="assistant-provider-pop" aria-label="Saved AI providers">
      <p>Applies to your next message. Existing runs keep their provider.</p>
      {providers.map((key) => <button type="button"
        key={key.provider} disabled={saving || key.provider === selected}
        onClick={() => void switchProvider(key.provider)}>
        {labels[key.provider] ?? key.provider}{key.default_model ? ` · ${key.default_model}` : ""}
        {key.provider === selected ? " · Selected" : ""}
      </button>)}
      {!providers.length ? <a href="/settings">Add a provider key in Settings</a> : null}
    </div> : null}
    {error ? <p role="alert" className="assistant-warning">{error}</p> : null}
  </div>;
}
