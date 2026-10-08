"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { IndexChart } from "@/components/markets/IndexChart";
import type { WorkspaceData } from "@/components/workspace/useWorkspaceData";
import { PortfolioRiskFlag, RollingRisk, getAlerts, getPortfolioRiskFlags, getRollingRisk } from "@/lib/api";
import { timeAgo } from "@/lib/markets";
import { formatDate, formatNumber, formatPercent, numeric } from "@/lib/overview";
import { MandateRow, MetricRow, RiskIssue, RiskRange, concentrationRows, diversificationRows, fraction, mandateRows, overallRisk, riskBrief, riskRanges, rollingSeries, systematicRows, tailRows } from "@/lib/portfolio-risk";
import s from "./risk/risk.module.css";

type AlertRow = { id: string; message: string; alert_type: string; created_at: string };
const pkr = (value: number | null) => value == null ? "—" : `PKR ${formatNumber(value, 0)}`;
const tone = (value: number | null) => value == null || value === 0 ? "" : value > 0 ? s.good : s.bad;

export function RiskTab({ portfolioId, data }: { portfolioId: string; data: WorkspaceData }) {
  const { summary, quant, exposure, compliance } = data;
  const [range, setRange] = useState<RiskRange>("1Y");
  const [rolling, setRolling] = useState<RollingRisk | null>(null);
  const [rollingError, setRollingError] = useState("");
  const [flags, setFlags] = useState<PortfolioRiskFlag[]>([]);
  const [alerts, setAlerts] = useState<AlertRow[]>([]);

  useEffect(() => {
    let active = true;
    setRolling(null); setRollingError("");
    void getRollingRisk(portfolioId).then(value => active && setRolling(value)).catch((e: Error) => active && setRollingError(e.message));
    void getPortfolioRiskFlags(portfolioId).then(value => active && setFlags(value.flags)).catch(() => undefined);
    void getAlerts(portfolioId, "active").then(rows => active && setAlerts(rows as unknown as AlertRow[])).catch(() => undefined);
    return () => { active = false; };
  }, [portfolioId]);

  const totalValue = numeric(summary?.total_value);
  const overall = useMemo(() => overallRisk(quant, totalValue), [quant, totalValue]);
  const series = useMemo(() => rollingSeries(rolling, range), [rolling, range]);
  const systematic = systematicRows(quant);
  const mandate = mandateRows(compliance, exposure);
  const breaches = mandate.filter(row => row.status === "BREACH");
  const notEvaluated = (compliance?.not_evaluated?.length ?? 0) + mandate.filter(row => row.status === "NOT_EVALUATED").length;
  const sectors = [...(exposure?.by_sector ?? [])].sort((a, b) => Number(b.weight_percent) - Number(a.weight_percent));
  const brief = riskBrief({ breaches: breaches.map(row => row.rule), notEvaluated, volatility: overall.volatility, topSector: sectors[0] ? `${sectors[0].sector} (${Number(sectors[0].weight_percent).toFixed(1)}%)` : undefined });

  const issues: RiskIssue[] = [
    ...(compliance?.violations ?? []).map((violation, index) => ({ id: `v${index}`, title: String(violation.label ?? violation.code ?? "Mandate breach"), detail: String(violation.message ?? ""), level: "High" as const, source: "Mandate compliance", when: null })),
    ...flags.map(flag => ({ id: `f${flag.code}`, title: flag.code.replaceAll("_", " "), detail: flag.message, level: flag.severity.toLowerCase() === "high" ? "High" as const : flag.severity.toLowerCase() === "medium" ? "Medium" as const : "Low" as const, source: "Portfolio risk flag", when: null })),
    ...alerts.map(alert => ({ id: alert.id, title: alert.alert_type.replaceAll("_", " "), detail: alert.message, level: "Medium" as const, source: "Monitoring alert", when: alert.created_at })),
  ];

  if (!summary && !quant) return <p className={s.empty}>Risk data is unavailable. The API returned no portfolio valuation or analytics.</p>;

  return (
    <div className={`rx ${s.layout}`}>
      <div className={s.main} data-portfolio-panel="content">
        <header className={s.kpis}>
          <Kpi label="Portfolio value" value={pkr(totalValue)} sub={summary ? `${formatPercent(summary.day_change_percent)} latest session` : undefined} subTone={tone(numeric(summary?.day_change_percent))} />
          <Kpi label="Total return (unrealized)" value={formatPercent(summary?.unrealized_gain_loss_percent)} tone={tone(numeric(summary?.unrealized_gain_loss_percent))} />
          <Kpi label="Annualized return" value={fraction(overall.annualReturn, 1, true)} tone={tone(overall.annualReturn)} sub="Modeled current allocation" />
          <Kpi label="Volatility (ann.)" value={fraction(overall.volatility)} />
        </header>

        {compliance?.status === "BREACH" || breaches.length ? (
          <div className={`${s.banner} ${s.bannerBad}`} role="alert"><strong>{breaches.length || compliance?.violations.length} mandate issue{(breaches.length || compliance?.violations.length) === 1 ? "" : "s"} require attention</strong><span>{(compliance?.violations ?? []).map(v => String(v.message ?? "")).filter(Boolean).join(" ")}</span></div>
        ) : compliance?.status === "PASS" ? (
          <div className={s.banner} role="status"><strong>Within mandate</strong><span>All evaluated IPS checks pass.</span></div>
        ) : (
          <div className={`${s.banner} ${s.bannerWarn}`} role="status"><strong>Mandate not fully evaluated</strong><span>Compliance data or IPS limits are missing. <Link className="rx-link" href={`/portfolios/${portfolioId}/ips` as never}>Review the IPS</Link></span></div>
        )}

        <section className={s.section}>
          <h2 className={s.h2}>Overall risk</h2>
          <div className={s.hero}>
            <Hero label="Annualized volatility" value={fraction(overall.volatility)} />
            <Hero label="1-day VaR (95%)" value={pkr(overall.var95?.amount ?? null)} note={overall.var95 ? `${fraction(overall.var95.fraction)} of portfolio` : "Unavailable"} />
            <Hero label="Expected shortfall (95%)" value={pkr(overall.es95?.amount ?? null)} note={overall.es95 ? `${fraction(overall.es95.fraction)} of portfolio` : "Unavailable"} />
            <Hero label="Maximum drawdown" value={fraction(overall.drawdown)} note={quant ? `As of ${formatDate(quant.data_cutoff)}` : undefined} />
          </div>
          <div className={s.chartHead}>
            <p className={s.hint}>Rolling {rolling?.window ?? 60}-day portfolio volatility (%)</p>
            <div className={s.ranges} role="group" aria-label="Chart range">{riskRanges.map(r => <button key={r} type="button" aria-pressed={range === r} onClick={() => setRange(r)}>{r}</button>)}</div>
          </div>
          {rollingError ? <p className={s.hint}>Rolling volatility could not be loaded: {rollingError}</p> : rolling ? <IndexChart points={series} name="Rolling volatility" height={240} compactAxis={false} /> : <p className={s.hint}>Loading rolling volatility…</p>}
          {rolling?.diagnostics?.length ? <p className={s.hint}>{rolling.diagnostics.join(" ")}</p> : null}
        </section>

        <div className={s.triple}>
          <MetricTable title="Market / systematic risk" rows={systematic.rows} unavailable={systematic.unavailable} />
          <MetricTable title="Concentration" rows={concentrationRows(exposure, quant)} />
          <MetricTable title="Tail risk" rows={tailRows(quant)} />
        </div>
        <div className={s.double}>
          <MetricTable title="Diversification" rows={diversificationRows(quant)} />
          <MandateTable rows={mandate} portfolioId={portfolioId} />
        </div>
        {quant?.warnings.length ? <p className={s.hint}>Model warnings: {quant.warnings.join(" · ")}</p> : null}
        <p className={s.hint}>Source: {summary?.data_source ?? "source unavailable"} · analytics cutoff {quant ? formatDate(quant.data_cutoff) : "unavailable"}. Period-over-period changes and a benchmark volatility line are not shown because the API does not provide them.</p>
      </div>

      <aside className={s.rail} data-portfolio-panel="context" aria-label="Risk brief">
        <h2 className={s.h2}>Risk brief</h2>
        <div className={s.brief}>{brief.map((line, i) => <p key={i} className={i === 0 ? s.briefLead : undefined}>{line}</p>)}</div>
        <p className={s.hint}>Assembled from the figures on this page, not generated text.</p>
        <h2 className={s.h2} style={{ marginTop: 28 }}>Key risk issues</h2>
        {issues.length ? issues.map(issue => (
          <div className={s.issue} key={issue.id}>
            <div><strong>{issue.title}</strong><p>{issue.detail}</p><small>{[issue.when ? timeAgo(issue.when) : null, issue.source].filter(Boolean).join(" · ")}</small></div>
            <span className={`rx-badge ${issue.level === "High" ? "bad" : issue.level === "Medium" ? "warn" : ""}`}>{issue.level}</span>
          </div>
        )) : <p className={s.hint}>No active risk issues from compliance checks, risk flags or monitoring alerts.</p>}
      </aside>
    </div>
  );
}

function Kpi({ label, value, sub, tone: t = "", subTone = "" }: { label: string; value: string; sub?: string; tone?: string; subTone?: string }) {
  return <div className={s.kpi}><p>{label}</p><strong className={t}>{value}</strong>{sub ? <small className={subTone}>{sub}</small> : null}</div>;
}
function Hero({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div><p>{label}</p><strong>{value}</strong>{note ? <small>{note}</small> : null}</div>;
}
function MetricTable({ title, rows, unavailable }: { title: string; rows: MetricRow[]; unavailable?: string }) {
  return <section className={s.table}><h3>{title}</h3>{unavailable ? <p className={s.hint}>{unavailable}</p> : null}<dl>{rows.map(row => <div key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}</dl></section>;
}
function MandateTable({ rows, portfolioId }: { rows: MandateRow[]; portfolioId: string }) {
  return <section className={s.table}><div className={s.tableHead}><h3>Mandate compliance</h3><Link className="rx-link" href={`/portfolios/${portfolioId}/ips` as never}>View IPS</Link></div>
    {rows.length ? <table><thead><tr><th>Rule</th><th>Limit</th><th>Current</th><th>Status</th></tr></thead><tbody>{rows.map(row => <tr key={row.rule}><td>{row.rule}</td><td>{row.limit}</td><td>{row.current}</td><td className={row.status === "BREACH" ? s.bad : row.status === "PASS" ? s.good : s.hint}>{row.status === "BREACH" ? "✕ Breach" : row.status === "PASS" ? "✓ Compliant" : "Not evaluated"}</td></tr>)}</tbody></table> : <p className={s.hint}>No IPS limits are configured, so no mandate checks were evaluated.</p>}</section>;
}
