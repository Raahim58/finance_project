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
  return <div className="border-b border-line px-3 py-2 text-xs">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span>{selected ? (labels[selected] ?? selected) : "Loading provider…"}
        {model ? <span className="ml-2 text-muted">{model}</span> : null}</span>
      <button type="button" className="btn btn-secondary" aria-expanded={opened}
        disabled={saving} onClick={() => setOpened(!opened)}>
        {saving ? "Switching…" : "Switch AI provider"}
      </button>
    </div>
    {opened ? <div className="mt-2 grid gap-2" aria-label="Saved AI providers">
      <p className="text-muted">Applies to your next message. Existing runs keep their provider.</p>
      {providers.map((key) => <button type="button" className="btn btn-secondary text-left"
        key={key.provider} disabled={saving || key.provider === selected}
        onClick={() => void switchProvider(key.provider)}>
        {labels[key.provider] ?? key.provider}{key.default_model ? ` · ${key.default_model}` : ""}
        {key.provider === selected ? " · Selected" : ""}
      </button>)}
      {!providers.length ? <a href="/settings">Add a provider key in Settings</a> : null}
    </div> : null}
    {error ? <p role="alert" className="mt-2 assistant-warning">{error}</p> : null}
  </div>;
}
