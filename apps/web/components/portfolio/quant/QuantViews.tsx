"use client";

import type { ReactNode } from "react";
import type { CapitalMarketAssumptions, CapmSml, EfficientFrontier, PortfolioQuant, ReturnDistribution, RiskBudget, RollingRisk } from "@/lib/api";
import { correlationExtremes, pctFraction, signedNumber, type ComparePoint } from "@/lib/portfolio-quant";
import type { ChartRef } from "./QuantChart";
import { QuantChart } from "./QuantChart";
import { capmOption, contributionOption, correlationOption, distributionOption, frontierOption, lineOption, markerColor, palette, rollingSeries } from "./chartOptions";
import type { Resource } from "./useQuantResources";
import s from "./quant.module.css";

export function Notes({ items }: { items: string[] }) {
  const unique = Array.from(new Set(items.filter(Boolean)));
  return unique.length ? <ul className={s.notes}>{unique.map(item => <li key={item}>{item}</li>)}</ul> : null;
}

export function Unavailable({ title, text, onRetry }: { title: string; text: string; onRetry?: () => void }) {
  return <div className={s.state} role="status"><strong>{title}</strong><span>{text}</span>{onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}</div>;
}

// Loading skeleton, timeout/failure with retry, then the view once data exists.
export function Gate<T>({ resource, label, children }: { resource: Resource<T>; label: string; children: (value: T) => ReactNode }) {
  if (resource.status === "idle" || resource.status === "loading") return <div className={s.skeleton} aria-busy="true" aria-label={`Loading ${label}`} />;
  if (resource.status === "error" || !resource.value) return <Unavailable title={`${label} request failed`} text={resource.error ?? "The model did not respond."} onRetry={resource.retry} />;
  return <>{children(resource.value)}</>;
}

export function FrontierView({ frontier, assumptions, points, showAssets, chartRef }: {
  frontier: EfficientFrontier; assumptions: CapitalMarketAssumptions | null; points: ComparePoint[]; showAssets: boolean; chartRef: ChartRef;
}) {
  if (!frontier.points.length) return <Unavailable title="Efficient frontier unavailable" text="The chart requires a feasible modeled universe." />;
  const drawn = points.filter(point => point.plottable);
  const assetCount = (assumptions?.securities ?? []).filter(item => item.volatility != null && item.expected_return != null).length;
  return <>
    <p className={s.caption}><b>{frontier.feasible_set_label}.</b> Annualized expected return and volatility of the risky sleeve (cash excluded), estimator {frontier.estimator.replaceAll("_", " ")}.</p>
    <QuantChart chartRef={chartRef} height={400} option={frontierOption(frontier, assumptions, drawn, showAssets)} />
    <div className={s.legend}>
      <span><i className={s.dot} style={{ background: palette.green }} />Efficient frontier</span>
      {drawn.map(point => <span key={point.id}><i className={s.dot} style={{ background: markerColor[point.id] }} />{point.label}</span>)}
      {showAssets && assetCount ? <span><i className={s.dot} style={{ background: palette.asset }} />Individual assets</span> : null}
    </div>
    <Notes items={[...(frontier.warnings ?? []),...(assumptions?.warnings ?? [])]} />
  </>;
}

export function CapmView({ capm, chartRef }: { capm: CapmSml; chartRef: ChartRef }) {
  if (!capm.available) return <Unavailable title="CAPM / SML unavailable" text={capm.diagnostics?.join(" ") || "An approved broad-index market proxy and an observed risk-free rate are required."} />;
  return <>
    <p className={s.caption}>Security market line from the observed risk-free rate and the CAPM market proxy; dots are each security&apos;s realized annual return against its beta.</p>
    <QuantChart chartRef={chartRef} height={400} option={capmOption(capm)} />
    <div className={s.stats}>
      <span>Risk-free <b>{pctFraction(capm.risk_free_rate, 2)}</b></span>
      <span>Market proxy return <b>{pctFraction(capm.market_return, 2)}</b></span>
      <span>Market risk premium <b>{pctFraction(capm.market_risk_premium, 2)}</b></span>
      <span>Market proxy <b>{capm.capm_market_proxy_symbol ?? capm.benchmark_symbol ?? "—"}</b></span>
    </div>
    <div className={s.budget}><table>
      <thead><tr><th>Security</th><th>Beta</th><th>Realized return</th><th>CAPM return</th><th>Jensen alpha</th></tr></thead>
      <tbody>{(capm.securities ?? []).map(item => <tr key={item.symbol}><td>{item.symbol}</td><td>{item.beta.toFixed(2)}</td><td>{pctFraction(item.realized_return, 1)}</td><td>{pctFraction(item.capm_return, 1)}</td><td className={item.jensen_alpha >= 0 ? s.positive : s.negative}>{pctFraction(item.jensen_alpha, 1, true)}</td></tr>)}</tbody>
    </table></div>
    <Notes items={capm.diagnostics ?? []} />
  </>;
}

export function CorrelationView({ quant, chartRef }: { quant: PortfolioQuant | null; chartRef: ChartRef }) {
  const matrix = quant?.correlation ?? [], symbols = quant?.symbols ?? [];
  if (!quant || !matrix.length) return <Unavailable title="Correlation unavailable" text="At least two holdings and aligned market observations are required." />;
  const high = correlationExtremes(matrix, symbols);
  return <>
    <p className={s.caption}>Pairwise correlation of daily returns across modeled holdings, {quant.sample_size} aligned observations to {quant.data_cutoff}.</p>
    <QuantChart chartRef={chartRef} height={Math.max(360, symbols.length * 44 + 90)} option={correlationOption(symbols, matrix)} />
    {high ? <div className={s.stats}><span>Highest pair <b>{high.pair} · {high.value.toFixed(2)}</b></span></div> : null}
  </>;
}

export function RollingView({ rolling, chartRef }: { rolling: RollingRisk; chartRef: ChartRef }) {
  if (!rolling.points?.length) return <Unavailable title="Rolling risk unavailable" text={rolling.diagnostics?.join(" ") || "More modeled current-allocation history is required."} />;
  const series = rollingSeries(rolling);
  return <>
    <p className={s.caption}><b>{rolling.window}-day rolling window</b> on the modeled current allocation ({rolling.observations} observations).</p>
    <QuantChart chartRef={chartRef} height={300} option={lineOption(series.labels, series.risk, value => pctFraction(value, 1))} />
    <QuantChart chartRef={{ current: null }} height={280} option={lineOption(series.labels, series.ratios, value => value.toFixed(2))} />
    <Notes items={rolling.diagnostics ?? []} />
  </>;
}

export function DistributionView({ distribution, chartRef }: { distribution: ReturnDistribution; chartRef: ChartRef }) {
  if (!distribution.bins?.length) return <Unavailable title="Return distribution unavailable" text={distribution.diagnostics?.join(" ") || "At least 30 ledger returns are required."} />;
  return <>
    <p className={s.caption}>Histogram of daily portfolio returns, {distribution.sample_size} observations.</p>
    <QuantChart chartRef={chartRef} height={360} option={distributionOption(distribution)} />
    <div className={s.stats}>
      <span>VaR 95 <b>{pctFraction(distribution.var_95, 2)}</b></span><span>ES 95 <b>{pctFraction(distribution.es_95, 2)}</b></span>
      <span>VaR 99 <b>{pctFraction(distribution.var_99, 2)}</b></span><span>ES 99 <b>{pctFraction(distribution.es_99, 2)}</b></span>
      <span>Skew <b>{signedNumber(distribution.skewness)}</b></span><span>Excess kurtosis <b>{signedNumber(distribution.excess_kurtosis)}</b></span>
    </div>
    <Notes items={distribution.diagnostics ?? []} />
  </>;
}

export function ContributionView({ quant, budget, chartRef }: { quant: PortfolioQuant | null; budget: RiskBudget | null; chartRef: ChartRef }) {
  const contributions = quant?.risk_contributions ?? {};
  if (!quant || !Object.keys(contributions).length) return <Unavailable title="Risk contribution unavailable" text="At least two holdings and 31 aligned market observations are required." />;
  return <>
    <p className={s.caption}>Share of modeled risky-sleeve volatility contributed by each holding.</p>
    <QuantChart chartRef={chartRef} height={Math.max(300, Object.keys(contributions).length * 38 + 40)} option={contributionOption(contributions)} />
    {budget?.items.length ? <div className={s.budget}>
      <h3>Total capital versus risky-sleeve risk</h3>
      <p className={s.caption}>Cash is included in total-capital weight; percentage risk is risky-sleeve based.</p>
      <table>
        <thead><tr><th>Security</th><th>Total-capital weight</th><th>Risky-sleeve weight</th><th>Risk contribution</th><th>Target risk</th><th>Residual</th></tr></thead>
        <tbody>{budget.items.map(row => <tr key={row.symbol}><td>{row.symbol}</td><td>{pctFraction(row.total_capital_weight)}</td><td>{pctFraction(row.risky_sleeve_weight)}</td><td>{pctFraction(row.percentage_risk)}</td><td>{pctFraction(row.target_risk)}</td><td>{pctFraction(row.residual, 1, true)}</td></tr>)}</tbody>
      </table>
      <Notes items={budget.diagnostics ?? []} />
    </div> : null}
  </>;
}
