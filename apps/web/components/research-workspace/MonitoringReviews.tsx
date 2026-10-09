"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { decideRecommendation, getRecommendations, type Portfolio } from "@/lib/api";
import { Details, Empty, date, display, human, styles } from "./Common";

type ReviewDecision = "reviewed" | "rejected" | "dismissed" | "resolved";
const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};

/** Stored monitoring/IPS review records retain their backend IDs and allocation links. */
export function MonitoringReviews({ portfolios, scope, onScopeChange }: {
  portfolios: Portfolio[];
  scope: string;
  onScopeChange: (scope: string) => void;
}) {
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    void getRecommendations().then(result => {
      if (active) setRows(result);
    }).catch(reason => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load review records.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  const scoped = rows.filter(row => !scope || row.portfolio_id === scope);
  const statuses = Array.from(new Set(scoped.map(row => String(row.status ?? "")))).filter(Boolean);
  const visible = scoped.filter(row => (!filter || row.status === filter)
    && `${row.message ?? ""} ${row.trigger_label ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  const detail = visible.find(row => String(row.id) === selected) ?? visible[0];
  const evidence = object(detail?.evidence);
  const effect = object(detail?.expected_effect);
  const uncertainty = object(detail?.uncertainty);
  const freshness = object(detail?.freshness);
  const allocation = object(detail?.linked_allocation);

  async function transition(decision: ReviewDecision) {
    if (!detail) return;
    setBusy(true);
    setError("");
    try {
      const updated = await decideRecommendation(String(detail.id), decision);
      setRows(previous => previous.map(row => row.id === detail.id ? { ...row, status: updated.status } : row));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update review status.");
    } finally { setBusy(false); }
  }

  return <div className={`${styles.workspace} ${styles.two}`}>
    <main data-portfolio-panel="content" className={styles.main}>
      <h2 className={styles.heading}>Reviews</h2>
      <p className={styles.sub}>Review recorded monitoring triggers and IPS breaches, their evidence, and linked portfolio proposals.</p>
      <div className={styles.toolbar}>
        <select className={styles.field} aria-label="Review portfolio" value={scope} onChange={event => {
          onScopeChange(event.target.value); setSelected(""); setFilter("");
        }}>
          <option value="">All portfolios</option>
          {portfolios.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}
        </select>
        <select className={styles.field} aria-label="Review status" value={filter} onChange={event => setFilter(event.target.value)}>
          <option value="">All statuses</option>
          {statuses.map(value => <option key={value} value={value}>{human(value)}</option>)}
        </select>
        <input className={styles.field} aria-label="Filter reviews" placeholder="Filter reviews" value={query} onChange={event => setQuery(event.target.value)}/>
      </div>
      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {loading ? <p className={styles.loading}>Loading review records…</p> : visible.length ? <>
        <div className={styles.tableWrap}><table className={styles.table}>
          <thead><tr><th>Review</th><th>Trigger</th><th>Status</th><th>Data cutoff</th></tr></thead>
          <tbody>{visible.map(row => {
            const cutoff = object(row.freshness);
            return <tr key={String(row.id)} aria-selected={detail?.id === row.id}>
              <td><button onClick={() => setSelected(String(row.id))}>{display(row.message)}</button></td>
              <td>{display(row.trigger_label ?? row.trigger)}</td>
              <td><span className={styles.badge}>{display(row.status)}</span></td>
              <td className={styles.nowrap}>{date(String(cutoff.as_of ?? cutoff.data_as_of ?? cutoff.latest_trade_date ?? cutoff.market_as_of ?? ""))}</td>
            </tr>;
          })}</tbody>
        </table></div>
        {detail ? <section className={styles.section}>
          <h3>{display(detail.message)}</h3>
          <Details rows={[
            ["Trigger", detail.trigger_label ?? detail.trigger], ["Status", detail.status],
            ["Portfolio", portfolios.find(row => row.id === detail.portfolio_id)?.name],
            ["Expected effect", effect.note ?? effect.reason], ["Uncertainty", uncertainty.note],
            ["Mandate relevance", evidence.classification], ["IPS limit", evidence.related_ips_limit],
            ["Linked allocation version", allocation.version],
          ]}/>
          {Array.isArray(evidence.checks) ? <section className={styles.section}>
            <h3>Constraint status</h3>
            <table className={styles.table}><thead><tr><th>Check</th><th>Status</th><th>Recorded value</th></tr></thead>
              <tbody>{evidence.checks.map((check, index) => {
                const row = object(check);
                return <tr key={index}><td>{display(row.label ?? row.key ?? row.code)}</td><td>{display(row.status)}</td><td>{display(row.message ?? row.actual ?? row.current_value)}</td></tr>;
              })}</tbody>
            </table>
          </section> : null}
          {Array.isArray(detail.ips_violation) ? detail.ips_violation.map((violation, index) => {
            const row = object(violation);
            return <p className={styles.note} key={index}>{display(row.message ?? row.label)}</p>;
          }) : null}
          <div className={styles.toolbar} style={{ marginTop: 24 }}>
            <button className={styles.button} disabled={busy} onClick={() => void transition("reviewed")}>Mark reviewed</button>
            <button className={styles.button} disabled={busy} onClick={() => void transition("rejected")}>Reject</button>
            <button className={styles.button} disabled={busy} onClick={() => void transition("dismissed")}>Dismiss</button>
            {Object.keys(allocation).length ? <button className={styles.button} disabled={busy} onClick={() => void transition("resolved")}>Resolve</button> : null}
            {detail.portfolio_id ? <Link className={styles.button} href={`/portfolios/${String(detail.portfolio_id)}/build?recommendation=${encodeURIComponent(String(detail.id))}` as never}>Open linked proposal →</Link> : null}
          </div>
        </section> : null}
      </> : !error ? <Empty title="No review records" text="Monitoring triggers and IPS breaches appear here when recorded."/> : null}
    </main>
    <aside data-portfolio-panel="context" className={styles.right}>
      <Details rows={[
        ["Rule type", evidence.rule_type], ["Rule threshold", evidence.rule_threshold],
        ["Current value", evidence.current_value], ["Related IPS limit", evidence.related_ips_limit],
        ["Freshness", Object.keys(freshness).length ? freshness : null],
      ]}/>
      <details className={styles.section}><summary>Recorded source evidence</summary>
        {Object.keys(evidence).length ? <pre className={styles.passage}>{JSON.stringify(evidence, null, 2)}</pre> : <p className={styles.note}>No evidence selected.</p>}
      </details>
      <section className={styles.section}><h3>Reasoning</h3><p className={styles.note}>{display(detail?.reasoning ?? uncertainty.note ?? effect.reason)}</p></section>
    </aside>
  </div>;
}
