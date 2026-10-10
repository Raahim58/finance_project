"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { Icon, IconName } from "@/components/Icon";
import { LLMKey, Preferences, clearToken, createLLMKey, deleteLLMKey, getLLMKeys, getPortfolios, getPreferences, getProfile, testLLMKey, updatePreferences } from "@/lib/api";
import { ANALYSIS_LENSES, CADENCES, NOTIFICATION_TOPICS, PROVIDERS, ProviderOption, modelOptions } from "./providers";

const SECTIONS: Array<[string, string, IconName]> = [["application", "Application", "settings"], ["providers", "AI providers", "assistant"], ["notifications", "Notifications", "bell"], ["security", "Security", "check"]];
const cap = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

export function SettingsWorkspace() {
  const section = useSearchParams().get("section") ?? "providers";
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [keys, setKeys] = useState<LLMKey[]>([]);
  const [loadError, setLoadError] = useState("");
  const [portfolioId, setPortfolioId] = useState<string | undefined>();

  useEffect(() => {
    let active = true;
    void Promise.all([getPreferences(), getLLMKeys()]).then(([p, k]) => { if (active) { setPrefs(p); setKeys(k); } }).catch((e: Error) => active && setLoadError(e.message));
    void getPortfolios().then(rows => active && setPortfolioId(rows.find(r => r.is_default && !r.archived_at)?.id)).catch(() => undefined);
    return () => { active = false; };
  }, []);

  async function savePrefs(patch: Partial<Preferences>) {
    const next = await updatePreferences(patch);
    setPrefs(next);
    return next;
  }

  return (
    <div className="rx rx-settings">
      <nav className="rx-subnav" aria-label="Settings sections">
        <h1 className="rx-subnav-title">Settings</h1>
        {SECTIONS.map(([id, label, icon]) => (
          <Link key={id} href={`/settings?section=${id}` as never} aria-current={section === id ? "page" : undefined}>
            <Icon name={icon} size={20} /><span className="grow">{label}</span><Icon name="chevron" size={16} />
          </Link>
        ))}
      </nav>
      <div>
        {loadError ? <p className="rx-error" role="alert" style={{ marginBottom: 20 }}>Settings could not be loaded: {loadError}</p> : null}
        {section === "providers" ? <><Providers prefs={prefs} keys={keys} setKeys={setKeys} savePrefs={savePrefs} /><Application prefs={prefs} savePrefs={savePrefs} compact /></> : null}
        {section === "application" ? <Application prefs={prefs} savePrefs={savePrefs} /> : null}
        {section === "notifications" ? <Notifications prefs={prefs} savePrefs={savePrefs} /> : null}
        {section === "security" ? <Security /> : null}
      </div>
      <aside aria-label="Privacy and scope">
        <h2 className="rx-h2">Privacy &amp; scope</h2>
        <div style={{ marginTop: 12 }}>
          <PrivacyItem icon="check" title="Keys encrypted at rest" text="Your API keys are stored encrypted and are never sent back to the browser after saving." />
          <PrivacyItem icon="company" title="Only the server uses saved keys" text="Keys are decrypted on the server immediately before a request to your provider." />
          <PrivacyItem icon="document" title="Investment mandate belongs to your portfolio IPS" text="AI analysis operates within the mandate defined in each portfolio’s IPS." />
        </div>
        {portfolioId ? <Link className="rx-btn rx-btn-outline rx-btn-sm" href={`/portfolios/${portfolioId}/ips` as never}>Open portfolio IPS</Link> : <p className="rx-hint">Create a portfolio to define its IPS.</p>}
      </aside>
    </div>
  );
}

function PrivacyItem({ icon, title, text }: { icon: IconName; title: string; text: string }) {
  return <div className="rx-privacy-item"><Icon name={icon} size={22} /><div><h3>{title}</h3><p>{text}</p></div></div>;
}

function Providers({ prefs, keys, setKeys, savePrefs }: { prefs: Preferences | null; keys: LLMKey[]; setKeys: (keys: LLMKey[]) => void; savePrefs: (p: Partial<Preferences>) => Promise<Preferences> }) {
  const active = prefs?.default_llm_provider;
  const [open, setOpen] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "note" | "error"; text: string } | null>(null);
  const expanded = open ?? active ?? null;

  async function makeDefault(provider: string) {
    try { await savePrefs({ default_llm_provider: provider }); setOpen(provider); setMessage(null); }
    catch (e) { setMessage({ tone: "error", text: e instanceof Error ? e.message : "Could not change provider" }); }
  }

  return (
    <section>
      <h1 className="rx-h1">AI providers</h1>
      <p className="rx-lede">Connect a provider to power company research, market analysis and portfolio insights across RAAHIM PSX. You can change the provider or model at any time.</p>
      {message ? <p className={message.tone === "error" ? "rx-error" : "rx-note"} role="status" style={{ marginTop: 16 }}>{message.text}</p> : null}
      <div style={{ marginTop: 18 }}>
        {PROVIDERS.map(provider => {
          const saved = keys.find(k => k.provider === provider.id && k.is_active) ?? keys.find(k => k.provider === provider.id);
          return <ProviderRow key={provider.id} provider={provider} saved={saved} isDefault={active === provider.id} expanded={expanded === provider.id}
            onToggle={() => setOpen(expanded === provider.id ? "" : provider.id)} onSelect={() => makeDefault(provider.id)}
            onSaved={async key => { setKeys([key, ...keys.filter(k => k.id !== key.id)]); await makeDefault(provider.id); setMessage({ tone: "note", text: `${provider.label} key saved and set as the active provider. The full key was not returned to the browser.` }); }}
            onRemoved={id => { setKeys(keys.filter(k => k.id !== id)); setMessage({ tone: "note", text: `${provider.label} key removed.` }); }} />;
        })}
      </div>
    </section>
  );
}

function ProviderRow({ provider, saved, isDefault, expanded, onToggle, onSelect, onSaved, onRemoved }: {
  provider: ProviderOption; saved?: LLMKey; isDefault: boolean; expanded: boolean;
  onToggle: () => void; onSelect: () => void; onSaved: (key: LLMKey) => Promise<void>; onRemoved: (id: string) => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const [reveal, setReveal] = useState(false);
  const [model, setModel] = useState(saved?.default_model ?? provider.models[0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { if (saved?.default_model) setModel(saved.default_model); }, [saved?.default_model]);
  const canSelect = Boolean(saved);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError("");
    try {
      const verdict = await testLLMKey(provider.id, apiKey, model);
      if (!verdict.valid) throw new Error(verdict.message);
      await onSaved(await createLLMKey(provider.id, apiKey, model));
      setApiKey("");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not save key"); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!saved) return;
    setBusy(true); setError("");
    try { await deleteLLMKey(saved.id); onRemoved(saved.id); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not remove key"); }
    finally { setBusy(false); }
  }

  return (
    <div className="rx-provider">
      <button type="button" role="radio" aria-checked={isDefault} aria-label={`Use ${provider.label}`} className="rx-radio" disabled={!canSelect} title={canSelect ? undefined : "Save a key to use this provider"} onClick={onSelect} />
      <span className="rx-logo" aria-hidden="true">{provider.mark}</span>
      <div><h3>{provider.label}{saved?.default_model ? ` · ${saved.default_model}` : ""}</h3><p>{isDefault ? "Configured provider" : saved ? "Key saved" : "Use your own API key"}</p></div>
      <button type="button" className="rx-btn rx-btn-outline rx-btn-sm" aria-expanded={expanded} onClick={onToggle}>{expanded ? "Hide" : saved ? "Manage" : "Add key"}</button>
      {expanded ? (
        <form className="rx-provider-body" onSubmit={submit}>
          <label className="rx-label">API key
            <span style={{ position: "relative", display: "block" }}>
              <input className="rx-input" type={reveal ? "text" : "password"} autoComplete="off" required minLength={4} value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={saved ? saved.masked_api_key : "Paste your API key"} />
              <button type="button" aria-label={reveal ? "Hide key" : "Show key"} onClick={() => setReveal(!reveal)} style={{ position: "absolute", right: 10, top: 12, border: 0, background: "none", cursor: "pointer", fontSize: 12 }}>{reveal ? "Hide" : "Show"}</button>
            </span>
          </label>
          <label className="rx-label">Model
            <select className="rx-select" value={model} onChange={e => setModel(e.target.value)}>{modelOptions(provider, saved?.default_model).map(m => <option key={m}>{m}</option>)}</select>
          </label>
          <button className="rx-btn" disabled={busy || !apiKey}>{busy ? "Checking…" : "Save key"}</button>
          <p className="rx-hint">{saved ? `Saved key ${saved.masked_api_key} stays masked. Enter a new key to replace it.` : "The key is validated, then encrypted before storage."}</p>
          {error ? <p className="rx-error" role="alert" style={{ gridColumn: "1 / -1" }}>{error}</p> : null}
          {saved ? <button type="button" className="rx-btn rx-btn-outline rx-btn-sm" style={{ width: "max-content" }} disabled={busy} onClick={remove}>Remove saved key</button> : null}
        </form>
      ) : null}
    </div>
  );
}

function Application({ prefs, savePrefs, compact = false }: { prefs: Preferences | null; savePrefs: (p: Partial<Preferences>) => Promise<Preferences>; compact?: boolean }) {
  const [status, setStatus] = useState("");
  async function change(patch: Partial<Preferences>) {
    setStatus("");
    try { await savePrefs(patch); setStatus("Saved."); } catch (e) { setStatus(e instanceof Error ? e.message : "Save failed"); }
  }
  const Heading = compact ? "h2" : "h1";
  return (
    <section className="rx-section" style={compact ? { marginTop: 40 } : undefined}>
      <Heading className={compact ? "rx-h2" : "rx-h1"}>Application</Heading>
      <p className={compact ? "rx-hint" : "rx-lede"} style={compact ? { marginTop: 6, fontSize: 14 } : undefined}>These settings control how RAAHIM PSX uses AI in your workspace.</p>
      <div className="rx-grid-2">
        <label className="rx-label">Preferred analysis lens
          <select className="rx-select" disabled={!prefs} value={prefs?.preferred_analysis_mode ?? ""} onChange={e => change({ preferred_analysis_mode: e.target.value })}>{ANALYSIS_LENSES.map(o => <option key={o} value={o}>{cap(o)}</option>)}</select>
        </label>
        <label className="rx-label">Notification cadence
          <select className="rx-select" disabled={!prefs} value={prefs?.followup_frequency ?? ""} onChange={e => change({ followup_frequency: e.target.value })}>{CADENCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
        </label>
        {!compact ? <>
          <label className="rx-label">Risk tolerance
            <select className="rx-select" disabled={!prefs} value={prefs?.risk_tolerance ?? ""} onChange={e => change({ risk_tolerance: e.target.value })}>{["conservative", "balanced", "aggressive"].map(o => <option key={o} value={o}>{cap(o)}</option>)}</select>
          </label>
          <label className="rx-label">Investment horizon
            <select className="rx-select" disabled={!prefs} value={prefs?.investment_horizon ?? ""} onChange={e => change({ investment_horizon: e.target.value })}>{["short-term", "medium-term", "long-term"].map(o => <option key={o} value={o}>{cap(o)}</option>)}</select>
          </label>
        </> : null}
      </div>
      {status ? <p className="rx-hint" role="status" style={{ marginTop: 10 }}>{status}</p> : null}
      {!compact ? <p className="rx-note" style={{ marginTop: 20 }}>Each portfolio’s mandate is set and revised in its IPS.</p> : null}
    </section>
  );
}

function Notifications({ prefs, savePrefs }: { prefs: Preferences | null; savePrefs: (p: Partial<Preferences>) => Promise<Preferences> }) {
  const [error, setError] = useState("");
  const current = (prefs?.notification_preferences ?? {}) as Record<string, boolean>;
  async function toggle(key: string) {
    setError("");
    try { await savePrefs({ notification_preferences: { ...current, [key]: !(current[key] ?? true) } }); window.dispatchEvent(new Event("psx-notification-prefs")); }
    catch (e) { setError(e instanceof Error ? e.message : "Save failed"); }
  }
  return (
    <section>
      <h1 className="rx-h1">Notifications</h1>
      <p className="rx-lede">Choose which events appear in your workspace alerts. Alerts are produced by portfolio monitoring rules.</p>
      <p className="rx-note" style={{ marginTop: 16 }}>Alerts are delivered in-app through the bell in the top bar. Turning a topic off hides it there. Email and push delivery are not connected.</p>
      {error ? <p className="rx-error" role="alert" style={{ marginTop: 12 }}>{error}</p> : null}
      <div style={{ marginTop: 12 }}>
        {NOTIFICATION_TOPICS.map(([key, title, text]) => (
          <div className="rx-toggle-row" key={key}><div><h3>{title}</h3><p>{text}</p></div>
            <button type="button" role="switch" aria-checked={current[key] ?? true} aria-label={title} className="rx-switch" disabled={!prefs} onClick={() => toggle(key)} /></div>
        ))}
      </div>
      <p style={{ marginTop: 20 }}><Link className="rx-link" href={"/monitoring" as never}>Manage monitoring rules →</Link></p>
    </section>
  );
}

function Security() {
  const router = useRouter();
  const [profile, setProfile] = useState<{ email: string; full_name?: string | null } | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { void getProfile().then(setProfile).catch((e: Error) => setError(e.message)); }, []);
  return (
    <section>
      <h1 className="rx-h1">Security</h1>
      <p className="rx-lede">Account access for this workspace.</p>
      {error ? <p className="rx-error" role="alert" style={{ marginTop: 16 }}>{error}</p> : null}
      <dl style={{ marginTop: 24, display: "grid", gap: 16 }}>
        <div><dt className="rx-hint">Name</dt><dd style={{ fontSize: 15 }}>{profile?.full_name || "—"}</dd></div>
        <div><dt className="rx-hint">Email</dt><dd style={{ fontSize: 15 }}>{profile?.email ?? "—"}</dd></div>
      </dl>
      <p className="rx-note" style={{ marginTop: 20 }}>Password change and session management are not available yet. Saved AI keys are encrypted and are never shown after saving.</p>
      <button className="rx-btn rx-btn-outline" style={{ marginTop: 24 }} onClick={() => { clearToken(); router.push("/login" as never); }}>Sign out</button>
    </section>
  );
}
