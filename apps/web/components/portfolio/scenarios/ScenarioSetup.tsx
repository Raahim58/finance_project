"use client";

import type { FormEvent } from "react";
import type { MacroRegime, ScenarioTemplate } from "@/lib/api";
import { templateChips, type CustomInput } from "@/lib/portfolio-scenarios";
import styles from "./scenarios.module.css";

export type Selection = { kind: "template"; id: string } | { kind: "custom" } | { kind: "replay" };
export type ReplayInput = { start: string; end: string };

type Props = {
  templates: ScenarioTemplate[]; templatesError: string | null; regime: MacroRegime | null;
  symbols: string[]; sectors: string[]; maxDate?: string | null;
  selection: Selection; onSelect: (selection: Selection) => void;
  custom: CustomInput; onCustom: (value: CustomInput) => void;
  replay: ReplayInput; onReplay: (value: ReplayInput) => void;
  running: boolean; onRun: () => void;
};

export function ScenarioSetup({ templates, templatesError, regime, symbols, sectors, maxDate, selection, onSelect, custom, onCustom, replay, onReplay, running, onRun }: Props) {
  const suggested = new Set(regime?.suggested_scenario_ids ?? []);
  const ordered = templates.slice().sort((a, b) => Number(suggested.has(b.id)) - Number(suggested.has(a.id)));
  const template = selection.kind === "template" ? templates.find(row => row.id === selection.id) : undefined;
  const factors = [...new Set(templates.flatMap(row => Object.keys(row.factor_shocks)))];
  const setCustom = (patch: Partial<CustomInput>) => onCustom({ ...custom, ...patch });
  const submit = (event: FormEvent) => { event.preventDefault(); onRun(); };
  const canRun = !running && (selection.kind !== "template" || Boolean(template)) && (selection.kind !== "replay" || Boolean(replay.start && replay.end));

  return <form className={styles.setup} onSubmit={submit}>
    <h2 className={styles.h2}>Setup</h2>
    <p className={styles.sub}>Apply a deterministic shock to stored holdings and prices to see the estimated impact.</p>
    <div className={styles.types} role="list" aria-label="Scenario type">
      {ordered.map(row => <button type="button" role="listitem" className={styles.type} aria-current={selection.kind === "template" && selection.id === row.id} key={row.id} onClick={() => onSelect({ kind: "template", id: row.id })}>
        <span>{row.name}</span>{suggested.has(row.id) ? <span className={styles.tag} title={`Suggested by current macro regime: ${regime?.regime ?? ""}`}>Suggested</span> : null}
      </button>)}
      <button type="button" role="listitem" className={styles.type} aria-current={selection.kind === "custom"} onClick={() => onSelect({ kind: "custom" })}>Custom shock</button>
      <button type="button" role="listitem" className={styles.type} aria-current={selection.kind === "replay"} onClick={() => onSelect({ kind: "replay" })}>Historical replay</button>
    </div>
    {templatesError ? <p className={styles.unavailable}>Scenario templates could not be loaded ({templatesError}). Custom shocks and historical replay remain available.</p> : null}
    {regime ? <p className={styles.hint} style={{ marginBottom: 12 }}>Macro regime: {regime.regime.replaceAll("_", " ")}. {regime.method_note}</p> : null}

    <div className={styles.params}>
      {template ? <>
        <h3>{template.name}</h3>
        <p className={styles.hint}>{template.description}</p>
        {templateChips(template).length || template.fallback_security_shock != null ? <div className={styles.chips}>
          {templateChips(template).map(chip => <span className={styles.chip} key={chip}>{chip}</span>)}
          {template.fallback_security_shock != null ? <span className={styles.chip}>Fallback per security {(template.fallback_security_shock * 100).toFixed(1)}%</span> : null}
        </div> : null}
        <p className={styles.hint}>Parameters are fixed by template version {template.version}; use Custom shock to change them. Requires: {template.required_mappings.join(", ") || "none listed"}.</p>
      </> : null}
      {selection.kind === "custom" ? <>
        <h3>Custom shock</h3>
        <label className={styles.field}>Security
          <span className={styles.inputRow}>
            <select className={styles.input} value={custom.symbol} onChange={event => setCustom({ symbol: event.target.value })}><option value="">None</option>{symbols.map(symbol => <option key={symbol}>{symbol}</option>)}</select>
            <input className={styles.input} type="number" step="any" placeholder="%" aria-label="Security shock, percent" value={custom.securityShock} onChange={event => setCustom({ securityShock: event.target.value })} disabled={!custom.symbol} />
          </span></label>
        <label className={styles.field}>Sector
          <span className={styles.inputRow}>
            <select className={styles.input} value={custom.sector} onChange={event => setCustom({ sector: event.target.value })}><option value="">None</option>{sectors.map(sector => <option key={sector}>{sector}</option>)}</select>
            <input className={styles.input} type="number" step="any" placeholder="%" aria-label="Sector shock, percent" value={custom.sectorShock} onChange={event => setCustom({ sectorShock: event.target.value })} disabled={!custom.sector} />
          </span></label>
        <label className={styles.field}>Factor
          <span className={styles.inputRow}>
            <input className={styles.input} list="scenario-factors" placeholder="e.g. a catalog factor" value={custom.factor} onChange={event => setCustom({ factor: event.target.value })} />
            <input className={styles.input} type="number" step="any" placeholder="%" aria-label="Factor shock, percent" value={custom.factorShock} onChange={event => setCustom({ factorShock: event.target.value })} disabled={!custom.factor.trim()} />
          </span></label>
        <datalist id="scenario-factors">{factors.map(factor => <option key={factor} value={factor} />)}</datalist>
        <p className={styles.hint}>Percent changes applied to price. A direct security shock overrides sector and factor mappings for that security. Factor names come from the template catalog; securities without a mapping receive no shock.</p>
      </> : null}
      {selection.kind === "replay" ? <>
        <h3>Historical replay</h3>
        <label className={styles.field}>Start date<input className={styles.input} type="date" required max={maxDate ?? undefined} value={replay.start} onChange={event => onReplay({ ...replay, start: event.target.value })} /></label>
        <label className={styles.field}>End date<input className={styles.input} type="date" required max={maxDate ?? undefined} value={replay.end} onChange={event => onReplay({ ...replay, end: event.target.value })} /></label>
        <p className={styles.hint}>Replays today&apos;s holdings over a past interval using stored prices. It is a counterfactual and is not saved to scenario history.</p>
      </> : null}
      <p className={styles.unavailable}>This engine applies one-step shocks. Duration and second-order effects (liquidity, tax, fees, feedback) are not modeled.</p>
      <button className={styles.runButton} disabled={!canRun}>{running ? "Running…" : selection.kind === "replay" ? "Run replay" : "Run"}</button>
    </div>
  </form>;
}
