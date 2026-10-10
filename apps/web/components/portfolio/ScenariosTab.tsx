"use client";

import { useMemo, useState } from "react";
import { deleteScenarioRun, runHistoricalReplay, runScenario, type HistoricalReplay, type ScenarioResult } from "@/lib/api";
import { customPayload, templatePayload, type CustomInput } from "@/lib/portfolio-scenarios";
import type { WorkspaceData } from "@/components/workspace/useWorkspaceData";
import { EmptyResult, ReplayResult, RunResult } from "./scenarios/ScenarioResults";
import { ScenarioHistory } from "./scenarios/ScenarioHistory";
import { ScenarioSetup, type ReplayInput, type Selection } from "./scenarios/ScenarioSetup";
import { useScenarioData } from "./scenarios/useScenarioData";
import styles from "./scenarios/scenarios.module.css";

type Active = { kind: "run"; id: string } | { kind: "replay"; result: HistoricalReplay } | { kind: "fresh" } | null;
const blankCustom: CustomInput = { symbol: "", securityShock: "", sector: "", sectorShock: "", factor: "", factorShock: "" };

export function ScenariosTab({ portfolioId, data, setMessage }: { portfolioId: string; data: WorkspaceData; setMessage: (message: string) => void }) {
  const scenario = useScenarioData(portfolioId, data.scenarios);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [active, setActive] = useState<Active>(null);
  const [custom, setCustom] = useState<CustomInput>(blankCustom);
  const [replay, setReplay] = useState<ReplayInput>({ start: "", end: "" });
  const [running, setRunning] = useState(false);

  const holdings = data.summary?.holdings ?? [];
  const symbols = holdings.map(row => row.symbol);
  const sectors = useMemo(() => [...new Set(holdings.map(row => row.sector).filter(Boolean))].sort(), [holdings]);
  const names = useMemo(() => Object.fromEntries(holdings.map(row => [row.symbol, row.name])), [holdings]);
  const extraById = useMemo(() => new Map((scenario.extras.value?.runs ?? []).map(row => [row.id, row])), [scenario.extras.value]);
  const current: Selection = selection ?? (scenario.templates.value[0] ? { kind: "template", id: scenario.templates.value[0].id } : { kind: "custom" });
  const shownRun = active?.kind === "run" ? scenario.runs.find(row => row.id === active.id) : active ? undefined : scenario.runs[0];

  async function run() {
    setRunning(true);
    try {
      if (current.kind === "replay") {
        const result = await runHistoricalReplay(portfolioId, replay.start, replay.end, true);
        setActive({ kind: "replay", result }); setMessage(`Replayed current holdings from ${replay.start} to ${replay.end}.`); return;
      }
      let payload: Record<string, unknown>;
      if (current.kind === "template") {
        const template = scenario.templates.value.find(row => row.id === current.id);
        if (!template) { setMessage("Select a scenario template."); return; }
        payload = templatePayload(template, symbols);
      } else {
        const built = customPayload(custom);
        if ("error" in built) { setMessage(built.error); return; }
        payload = built.payload;
      }
      const result: ScenarioResult = await runScenario(portfolioId, payload);
      setActive({ kind: "run", id: result.id });
      await scenario.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Scenario failed");
    } finally { setRunning(false); }
  }

  async function remove(run: ScenarioResult) {
    if (!window.confirm(`Delete "${run.name}" from history?`)) return;
    try {
      await deleteScenarioRun(portfolioId, run.id);
      if (active?.kind === "run" && active.id === run.id) setActive(null);
      await scenario.refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not delete scenario");
    }
  }

  if (!scenario.loaded) return <div className={styles.layout} aria-busy="true" aria-label="Loading scenarios">
    <aside className={styles.setup}><h2 className={styles.h2}>Setup</h2><div className={styles.skeletonBlock} style={{ height: 300, marginTop: 20 }} /></aside>
    <section className={styles.results}><h2 className={styles.h2}>Results</h2><div className={styles.skeletonBlock} style={{ height: 120, marginTop: 20 }} /><div className={styles.skeletonBlock} style={{ height: 260, marginTop: 20 }} /></section>
    <aside className={styles.history}><h2 className={styles.h2}>History</h2><div className={styles.skeletonBlock} style={{ height: 200, marginTop: 20 }} /></aside>
  </div>;
  const extrasNote = scenario.extras.error ? "Volatility estimates are unavailable from this API build." : null;
  return <div className={styles.layout}>
    <ScenarioSetup templates={scenario.templates.value} templatesError={scenario.templates.error} regime={scenario.regime.value}
      symbols={symbols} sectors={sectors as string[]} maxDate={data.summary?.data_freshness_date}
      selection={current} onSelect={setSelection} custom={custom} onCustom={setCustom} replay={replay} onReplay={setReplay} running={running} onRun={() => void run()} />
    {active?.kind === "replay" ? <ReplayResult replay={active.result} websites={scenario.websites} />
      : shownRun ? <RunResult result={shownRun} extra={extraById.get(shownRun.id)} extrasNote={extrasNote} templates={scenario.templates.value} names={names} websites={scenario.websites} volatilityMethod={scenario.extras.value?.volatility_method} />
        : <EmptyResult text="Choose a scenario type, then run it. Results are computed from stored holdings and database prices." />}
    <ScenarioHistory runs={scenario.runs} extras={extraById} activeId={shownRun?.id ?? null}
      onSelect={run => setActive({ kind: "run", id: run.id })} onDelete={run => void remove(run)} onNew={() => { setActive({ kind: "fresh" }); setSelection(null); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
  </div>;
}
