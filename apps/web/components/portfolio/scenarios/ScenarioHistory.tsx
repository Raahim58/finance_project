"use client";

import { useState } from "react";
import type { ScenarioResult } from "@/lib/api";
import type { ScenarioRunExtra } from "@/lib/api/portfolio-scenarios";
import { formatPkr, formatPp, formatRunTime, formatSigned, tone, typeLabel } from "@/lib/portfolio-scenarios";
import styles from "./scenarios.module.css";

const VISIBLE = 6;

export function ScenarioHistory({ runs, extras, activeId, onSelect, onDelete, onNew }: {
  runs: ScenarioResult[]; extras: Map<string, ScenarioRunExtra>; activeId: string | null; onSelect: (run: ScenarioResult) => void; onDelete: (run: ScenarioResult) => void; onNew: () => void;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? runs : runs.slice(0, VISIBLE);
  return <aside className={styles.history} aria-label="History">
    <div className={styles.historyHead}><h2 className={styles.h2}>History</h2><button className={styles.secondary} onClick={onNew}>+ New</button></div>
    {runs.length ? <div className={styles.historyList}>{shown.map(run => {
      const extra = extras.get(run.id), when = formatRunTime(extra?.created_at), label = typeLabel(extra?.scenario_type);
      return <div className={styles.runRow} key={run.id}><button className={styles.run} aria-current={activeId === run.id} onClick={() => onSelect(run)}>
        <span className={styles.runTop}><strong>{run.name}</strong>{label ? <span className={styles.badge}>{label}</span> : null}</span>
        <span className={styles.runDate} style={{ display: "block" }}>{when ?? `Data as of ${run.data_cutoff}`}</span>
        <span className={styles.runStats}>
          <span><b className={styles[tone(run.pnl_percent)]}>{formatSigned(run.pnl_percent)}</b>Portfolio impact</span>
          <span><b className={styles[tone(run.pnl)]}>{formatPkr(run.pnl)}</b>PKR impact</span>
          <span><b>{extra?.volatility_change != null ? formatPp(extra.volatility_change) : "—"}</b>Volatility</span>
        </span>
      </button><button className={styles.runDelete} aria-label={`Delete ${run.name}`} title="Delete" onClick={() => onDelete(run)}>🗑</button></div>;
    })}</div> : <div className={styles.empty} style={{ marginTop: 14, minHeight: 140 }}><span>No runs yet.</span></div>}
    {runs.length > VISIBLE ? <button className={styles.viewAll} onClick={() => setAll(value => !value)}>{all ? "Show fewer" : `View all scenarios (${runs.length}) →`}</button> : null}
  </aside>;
}
