"use client";

import { ComplianceTable } from "@/components/DecisionTables";
import { CompanyLogo } from "@/components/markets/CompanyLogo";
import type { HistoricalReplay, ScenarioResult, ScenarioTemplate } from "@/lib/api";
import type { ScenarioRunExtra } from "@/lib/api/portfolio-scenarios";
import { numeric } from "@/lib/overview";
import { barWidth, formatPkr, formatPp, formatRunTime, formatSigned, holdingImpacts, replayContributions, sectorImpacts, shockChips, templateForRun, tone } from "@/lib/portfolio-scenarios";
import styles from "./scenarios.module.css";

const pctPlain = (value: number | null | undefined) => numeric(value) == null ? "—" : `${((value as number) * 100).toFixed(1)}%`;

function Bar({ value, rows }: { value: number | null; rows: Array<number | null> }) {
  return <div className={styles.barTrack}><div className={`${styles.bar} ${(value ?? 0) > 0 ? styles.up : ""}`} style={{ width: `${barWidth(value, rows)}%` }} /></div>;
}

export function RunResult({ result, extra, extrasNote, templates, names, websites, volatilityMethod }: {
  result: ScenarioResult; extra?: ScenarioRunExtra; extrasNote: string | null; templates: ScenarioTemplate[];
  names: Record<string, string>; websites: Record<string, string | null>; volatilityMethod?: string;
}) {
  const holdings = holdingImpacts(result, names), sectors = sectorImpacts(result);
  const template = templateForRun(result.name, templates);
  const when = formatRunTime(extra?.created_at);
  const chips = shockChips(extra?.shocks);
  const unmapped = holdings.filter(row => row.unmapped).map(row => row.symbol);
  const vol = extra?.volatility_change;
  return <section data-portfolio-panel="content" className={styles.results} aria-label="Results">
    <div className={styles.resultHead}>
      <div><h2 className={styles.h2}>Results</h2><div className={styles.runTitle}>{result.name}</div></div>
      <div className={styles.meta}><span className={styles.badge}>Deterministic</span><span>{when ? `Run on ${when}` : `Data as of ${result.data_cutoff}`}</span></div>
    </div>
    {template?.description ? <p className={styles.desc}>{template.description}</p> : null}
    {chips.length ? <div className={styles.chips} style={{ marginTop: 10 }}>{chips.map(chip => <span className={styles.chip} key={chip}>{chip}</span>)}</div> : null}

    <div className={styles.stats}>
      <div className={styles.stat}><span className={styles.statLabel}>Portfolio impact</span>
        <b className={`${styles.statValue} ${styles[tone(result.pnl_percent)]}`}>{formatSigned(result.pnl_percent)}</b>
        <span className={styles.statNote}>{formatPkr(result.pnl)}</span></div>
      <div className={styles.stat}><span className={styles.statLabel}>Change in volatility</span>
        {vol != null ? <><b className={styles.statValue}>{formatPp(vol)}</b><span className={styles.statNote} title={volatilityMethod}>From {pctPlain(extra?.volatility_before)} to {pctPlain(extra?.volatility_after)}</span></>
          : <><b className={`${styles.statValue} ${styles.muted}`}>—</b><span className={styles.statNote}>{extra?.volatility_unavailable_reason ?? extrasNote ?? "Not provided for this run."}</span></>}</div>
      <div className={styles.stat}><span className={styles.statLabel}>Benchmark impact estimate</span>
        <b className={`${styles.statValue} ${styles.muted}`}>—</b><span className={styles.statNote}>Not provided: this scenario engine does not shock index levels.</span></div>
    </div>
    {vol != null && volatilityMethod ? <p className={styles.hint}>{volatilityMethod}</p> : null}
    <p className={styles.hint}>Value before {formatPkr(result.portfolio_value, false)} → after {formatPkr(result.stressed_portfolio_value, false)}. Impacts are first-order, model-assumed price changes, not forecasts.</p>

    <div className={styles.section}>
      <h3>Impact by holding</h3>
      {holdings.length ? <div className={styles.tableWrap}><table className={styles.table}>
        <thead><tr><th>Symbol</th><th>Name</th><th className={styles.num}>Portfolio weight</th><th className={styles.num}>Price impact</th><th className={styles.num}>Contribution to portfolio</th><th /></tr></thead>
        <tbody>{holdings.map(row => <tr key={row.symbol}>
          <td><span className={styles.sym}><CompanyLogo symbol={row.symbol} website={websites[row.symbol]} size={22} />{row.symbol}</span></td>
          <td className={styles.nameCell} title={row.name ?? row.sector ?? undefined}>{row.name ?? row.sector ?? "—"}</td>
          <td className={styles.num}>{pctPlain(row.weight)}</td>
          <td className={`${styles.num} ${styles[tone(row.priceImpact)]}`}>{row.unmapped ? "No mapping" : formatSigned(row.priceImpact)}</td>
          <td className={`${styles.num} ${styles[tone(row.contribution)]}`}>{formatSigned(row.contribution, 2)}</td>
          <td className={styles.barCell}><Bar value={row.contribution} rows={holdings.map(item => item.contribution)} /></td>
        </tr>)}</tbody></table></div> : <p className={styles.unavailable}>This run stored no per-holding positions.</p>}
      {unmapped.length ? <p className={`${styles.note} ${styles.warn}`}>Coverage warning: {unmapped.join(", ")} received no sector or factor mapping and therefore a zero shock. Their impact is understated rather than measured.</p> : null}
    </div>

    <div className={styles.section}>
      <h3>Sector impact (portfolio)</h3>
      {sectors.length ? <div className={styles.tableWrap}><table className={styles.table}>
        <thead><tr><th>Sector</th><th className={styles.num}>Portfolio weight</th><th className={styles.num}>Sector impact</th><th className={styles.num}>Contribution</th><th /></tr></thead>
        <tbody>{sectors.map(row => <tr key={row.sector}>
          <td>{row.sector}</td><td className={styles.num}>{pctPlain(row.weight)}</td>
          <td className={`${styles.num} ${styles[tone(row.impact)]}`}>{formatSigned(row.impact)}</td>
          <td className={`${styles.num} ${styles[tone(row.contribution)]}`}>{formatSigned(row.contribution, 2)}</td>
          <td className={styles.barCell}><Bar value={row.contribution} rows={sectors.map(item => item.contribution)} /></td>
        </tr>)}</tbody></table></div> : <p className={styles.unavailable}>This run stored no sector contributions.</p>}
    </div>

    <div className={styles.section}>
      <h3>Stressed IPS compliance</h3>
      <ComplianceTable status={result.compliance.status} checks={result.compliance.checks} violations={result.compliance.violations} not_evaluated={result.compliance.not_evaluated} />
    </div>
    {result.assumptions.length ? <div className={styles.section}><h3>Assumptions and limits</h3><ul className={styles.notes}>{result.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
  </section>;
}

export function ReplayResult({ replay, websites }: { replay: HistoricalReplay; websites: Record<string, string | null> }) {
  const sectors = replayContributions(replay);
  const rows = replay.positions.map(row => ({ symbol: String(row.symbol ?? ""), sector: typeof row.sector === "string" ? row.sector : null, available: row.available === true, reason: typeof row.reason === "string" ? row.reason : null, start: numeric(row.start_value), end: numeric(row.end_value), pnl: numeric(row.pnl), ret: numeric(row.return) }));
  const values = replay.path.map(point => point.value), low = Math.min(...values), high = Math.max(...values);
  const points = values.map((value, index) => `${values.length > 1 ? index / (values.length - 1) * 300 : 0},${high === low ? 50 : 50 - (value - low) / (high - low) * 46}`).join(" ");
  return <section data-portfolio-panel="content" className={styles.results} aria-label="Historical replay results">
    <div className={styles.resultHead}>
      <div><h2 className={styles.h2}>Results</h2><div className={styles.runTitle}>Historical replay · {replay.start_date} to {replay.end_date}</div></div>
      <div className={styles.meta}><span className={styles.badge}>{replay.counterfactual ? "Counterfactual replay" : "Ledger replay"}</span><span>Not saved to history</span></div>
    </div>
    <p className={styles.desc}>{replay.assumption}.</p>
    <div className={styles.stats}>
      <div className={styles.stat}><span className={styles.statLabel}>Replay return</span><b className={`${styles.statValue} ${styles[tone(replay.return)]}`}>{formatSigned(replay.return)}</b><span className={styles.statNote}>{formatPkr(replay.pnl)}</span></div>
      <div className={styles.stat}><span className={styles.statLabel}>Maximum drawdown</span><b className={`${styles.statValue} ${styles[tone(replay.max_drawdown)]}`}>{formatSigned(replay.max_drawdown)}</b><span className={styles.statNote}>{replay.recovery_days != null ? `Recovered in ${replay.recovery_days} days` : "Not recovered within the window"}</span></div>
      <div className={styles.stat}><span className={styles.statLabel}>Value</span><b className={styles.statValue} style={{ fontSize: 22 }}>{formatPkr(replay.end_value, false)}</b><span className={styles.statNote}>From {formatPkr(replay.start_value, false)}</span></div>
    </div>
    {values.length > 1 ? <svg className={styles.replayPath} viewBox="0 0 300 54" preserveAspectRatio="none" role="img" aria-label="Replayed portfolio value path"><polyline points={points} fill="none" stroke="#00875a" strokeWidth="1.5" vectorEffect="non-scaling-stroke" /></svg> : <p className={styles.unavailable}>Too few aligned price dates to draw a value path.</p>}
    <div className={styles.section}><h3>Impact by holding</h3><div className={styles.tableWrap}><table className={styles.table}>
      <thead><tr><th>Symbol</th><th>Sector</th><th className={styles.num}>Start value</th><th className={styles.num}>End value</th><th className={styles.num}>Return</th><th className={styles.num}>P&amp;L</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.symbol}>
        <td><span className={styles.sym}><CompanyLogo symbol={row.symbol} website={websites[row.symbol]} size={22} />{row.symbol}</span></td><td className={styles.nameCell}>{row.sector ?? "—"}</td>
        {row.available ? <><td className={styles.num}>{formatPkr(row.start, false)}</td><td className={styles.num}>{formatPkr(row.end, false)}</td><td className={`${styles.num} ${styles[tone(row.ret)]}`}>{formatSigned(row.ret)}</td><td className={`${styles.num} ${styles[tone(row.pnl)]}`}>{formatPkr(row.pnl)}</td></> : <td colSpan={4} className={styles.muted}>{row.reason ?? "Price history unavailable"}</td>}
      </tr>)}</tbody></table></div></div>
    {sectors.length ? <div className={styles.section}><h3>Sector impact (portfolio)</h3><div className={styles.tableWrap}><table className={styles.table}>
      <thead><tr><th>Sector</th><th className={styles.num}>P&amp;L</th><th className={styles.num}>Contribution</th><th /></tr></thead>
      <tbody>{sectors.map(row => <tr key={row.sector}><td>{row.sector}</td><td className={`${styles.num} ${styles[tone(row.pnl)]}`}>{formatPkr(row.pnl)}</td><td className={`${styles.num} ${styles[tone(row.contribution)]}`}>{formatSigned(row.contribution, 2)}</td><td className={styles.barCell}><Bar value={row.contribution} rows={sectors.map(item => item.contribution)} /></td></tr>)}</tbody></table></div></div> : null}
    <p className={`${styles.note} ${styles.warn}`}><strong>Total-return limitation.</strong> {replay.total_return_unavailable_reason}</p>
  </section>;
}

export function EmptyResult({ text }: { text: string }) {
  return <section data-portfolio-panel="content" className={styles.results}><h2 className={styles.h2}>Results</h2><div className={styles.empty} style={{ marginTop: 16 }}><strong>No scenario selected</strong><span>{text}</span></div></section>;
}
