"use client";

import { AssistantControls } from "@/components/AssistantControls";
import { useState, type ReactNode } from "react";
import type { CapitalMarketAssumptions, EfficientFrontier } from "@/lib/api";
import { formatDate, humanize, numeric } from "@/lib/overview";
import { pctFraction, riskFreeRate, type ComparePoint } from "@/lib/portfolio-quant";
import { markerColor } from "./chartOptions";
import s from "./quant.module.css";

type Props = {
  metrics: ReactNode;
  onRetryAssumptions?: () => void;
  assumptions: CapitalMarketAssumptions | null; frontier: EfficientFrontier | null; points: ComparePoint[];
  checked: Record<string, boolean>; onToggle: (id: string) => void; showAssets: boolean; onToggleAssets: () => void; assetsAvailable: boolean;
  canPng: boolean; canCsv: boolean; onPng: () => void; onCsv: () => void;
};

// Every assumption is shown read-only: the backend fixes the estimator, constraints and risk-free
// source, so none of them is offered as a selectable option.
export function QuantRail(props: Props) {
  const { assumptions, frontier, points } = props;
  const [menu, setMenu] = useState(false);
  const rf = riskFreeRate(assumptions, frontier);
  const rfMeta = (assumptions?.risk_free ?? null) as Record<string, unknown> | null;
  const estimator = (assumptions?.estimator ?? {}) as Record<string, unknown>;
  const constraints = (frontier?.assumptions ?? {}) as Record<string, unknown>;
  const maxWeight = numeric(constraints.maximum_instrument_weight);
  const covShrink = numeric(estimator.covariance_shrinkage), retShrink = numeric(estimator.expected_return_shrinkage);
  const constraintText = frontier
    ? [constraints.long_only ? "Long only" : null, maxWeight != null ? `max ${pctFraction(maxWeight, 0)} per instrument` : null].filter(Boolean).join(", ") || "Unconstrained"
    : "—";
  const Row = ({ label, value, note }: { label: string; value: string; note?: string }) => <div className={s.row}><dt>{label}</dt><dd>{value}{note ? <small>{note}</small> : null}</dd></div>;
  return <aside className={s.rail} aria-label="Quant assumptions and comparison">
    <div className={s.askControls}><AssistantControls /></div>
    <section className={s.railSection}>
      <h2 className={s.railTitle}>Model assumptions</h2>
      <dl className={s.rows}>
        <Row label="Risk-free rate" value={rf == null ? "Unavailable" : pctFraction(rf, 2)}
          note={rf == null ? "No observed effective-dated series" : [rfMeta?.series_key ? String(rfMeta.series_key) : null, rfMeta?.effective_date ? `as of ${formatDate(String(rfMeta.effective_date))}` : null].filter(Boolean).join(" · ")} />
        <Row label="Covariance method" value={estimator.covariance_method ? humanize(String(estimator.covariance_method)) : "—"} note={covShrink != null ? `Shrinkage ${pctFraction(covShrink, 0)}` : undefined} />
        <Row label="Expected return" value={estimator.expected_return_method ? humanize(String(estimator.expected_return_method)) : "—"} note={retShrink != null ? `Shrinkage ${pctFraction(retShrink, 0)}` : undefined} />
        <Row label="Sample" value={assumptions ? `${assumptions.sample_size.toLocaleString("en-PK")} obs.` : "—"} note={assumptions ? `${formatDate(assumptions.sample_start)} to ${formatDate(assumptions.data_cutoff)} · ${assumptions.annualization}-day year` : undefined} />
        <Row label="Cash" value={frontier ? "Excluded" : "—"} />
        <Row label="Sector / IPS limits" value={frontier ? "Not applied" : "—"} />
        <Row label="Optimization constraint" value={constraintText} note={frontier ? "Cash, sector and IPS limits are not applied here" : undefined} />
        <Row label="Rebalancing" value="Not modeled" note="Frontier is a one-period comparison" />
      </dl>
      <p className={s.readonly}>{assumptions ? "Assumptions are fixed by the model and shown read-only." : props.onRetryAssumptions ? <>Model assumptions could not be loaded. <button type="button" className={s.link} onClick={props.onRetryAssumptions}>Retry</button></> : "Loading model assumptions."}</p>
    </section>
    <section className={s.railSection}>
      <h2 className={s.railTitle}>Compare portfolios</h2>
      <ul className={s.compare}>
        {points.map(point => {
          const disabled = !point.plottable;
          const note = disabled
            ? [point.expectedReturn != null && point.id === "benchmark" ? `${pctFraction(point.expectedReturn, 1)} expected return` : null, point.reason].filter(Boolean).join(" · ")
            : `${pctFraction(point.expectedReturn, 1)} return, ${pctFraction(point.volatility, 1)} risk`;
          return <li key={point.id}><label data-disabled={disabled}>
            <input type="checkbox" disabled={disabled} checked={!disabled && Boolean(props.checked[point.id])} onChange={() => props.onToggle(point.id)} />
            <span className={s.compareName}><i className={s.dot} style={{ background: markerColor[point.id] }} />{point.label}</span>
            <span className={s.compareNote}>{note}</span>
          </label></li>;
        })}
        <li><label data-disabled={!props.assetsAvailable}>
          <input type="checkbox" disabled={!props.assetsAvailable} checked={props.assetsAvailable && props.showAssets} onChange={props.onToggleAssets} />
          <span className={s.compareName}>Individual assets</span>
          <span className={s.compareNote}>{props.assetsAvailable ? "Per-security return and volatility" : "Per-security estimates unavailable"}</span>
        </label></li>
      </ul>
    </section>
    <section className={s.railSection}><h2 className={s.railTitle}>Selected portfolio metrics</h2>{props.metrics}<p className={s.readonly}>Model output, not forecast.</p></section>
    <div className={s.exportWrap}>
      {menu ? <div className={s.exportMenu} role="menu">
        <button type="button" role="menuitem" disabled={!props.canPng} onClick={() => { props.onPng(); setMenu(false); }}>Chart image (PNG){props.canPng ? "" : " — no chart loaded"}</button>
        <button type="button" role="menuitem" disabled={!props.canCsv} onClick={() => { props.onCsv(); setMenu(false); }}>Chart data (CSV){props.canCsv ? "" : " — no data loaded"}</button>
      </div> : null}
      <button type="button" className={s.exportBtn} aria-haspopup="menu" aria-expanded={menu} disabled={!props.canPng && !props.canCsv} onClick={() => setMenu(open => !open)}>Export chart ▾</button>
      <p className={s.exportHint}>Export the active chart as an image or CSV</p>
    </div>
  </aside>;
}
