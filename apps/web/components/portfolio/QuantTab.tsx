"use client";

import { useMemo, useRef, useState } from "react";
import type ReactECharts from "echarts-for-react";
import type { WorkspaceData } from "@/components/workspace/useWorkspaceData";
import { comparePoints, delta, exportRows, kpiFor, pctFraction, quantTabs, riskFreeRate, signedNumber, toCsv, type QuantTabId } from "@/lib/portfolio-quant";
import { CapmView, ContributionView, CorrelationView, DistributionView, FrontierView, Gate, Notes, RollingView, Unavailable } from "./quant/QuantViews";
import { QuantRail } from "./quant/QuantRail";
import { useQuantResources } from "./quant/useQuantResources";
import s from "./quant/quant.module.css";

function download(href: string, filename: string) {
  const link = document.createElement("a");
  link.href = href; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove();
}

export function QuantTab({ portfolioId, data, setMessage, loading }: { portfolioId: string; data: WorkspaceData; setMessage: (message: string) => void; loading: boolean }) {
  const [tab, setTab] = useState<QuantTabId>("frontier");
  const [overrides, setOverrides] = useState<Record<string, boolean>>({});
  const [showAssets, setShowAssets] = useState(true);
  const chartRef = useRef<ReactECharts | null>(null);
  const resources = useQuantResources(portfolioId, tab, Boolean(data.quant));
  const quant = data.quant ?? resources.quant.value;
  const frontier = resources.frontier.value, assumptions = resources.assumptions.value;

  const points = useMemo(() => comparePoints(frontier, assumptions, quant), [frontier, assumptions, quant]);
  // Default selection: current plus the first drawable alternative; user toggles override it.
  const defaultAlternative = points.find(point => point.tone === "alternative" && point.plottable)?.id;
  const checked = useMemo(() => {
    const result: Record<string, boolean> = {};
    for (const point of points) result[point.id] = point.id in overrides ? overrides[point.id] : point.id === "current" || point.id === defaultAlternative;
    return result;
  }, [points, overrides, defaultAlternative]);
  const visible = points.filter(point => checked[point.id] && point.plottable);
  const rf = riskFreeRate(assumptions, frontier);
  const current = points.find(point => point.id === "current");
  const focus = visible.find(point => point.tone === "alternative") ?? current;
  const comparing = focus && current && focus.id !== current.id;
  const kpi = kpiFor(focus, rf, quant), base = kpiFor(current, rf, quant);
  const assetsAvailable = (assumptions?.securities ?? []).some(item => item.volatility != null && item.expected_return != null);

  const rows = exportRows(tab, { frontier, assumptions, capm: resources.capm.value, rolling: resources.rolling.value, distribution: resources.distribution.value, quant });
  const filename = `quant-${tab}-${portfolioId.slice(0, 8)}`;
  const png = () => {
    const url = chartRef.current?.getEchartsInstance().getDataURL({ type: "png", pixelRatio: 2, backgroundColor: "#fcfaf5" });
    if (url) download(url, `${filename}.png`); else setMessage("No chart is available to export.");
  };
  const csv = () => {
    if (!rows) return setMessage("No chart data is available to export.");
    const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" }));
    download(url, `${filename}.csv`); URL.revokeObjectURL(url);
  };

  const tone = (value: number | null, goodWhenHigher: boolean) => value == null || value === 0 ? "" : (value > 0) === goodWhenHigher ? s.positive : s.negative;
  const kpis: Array<{ label: string; value: string; delta: number | null; text: string; good: boolean | null }> = [
    { label: "Expected return (ann.)", value: pctFraction(kpi.expectedReturn, 1), delta: delta(kpi.expectedReturn, base.expectedReturn), text: "", good: true },
    { label: "Volatility (ann.)", value: pctFraction(kpi.volatility, 1), delta: delta(kpi.volatility, base.volatility), text: "", good: null },
    { label: "Sharpe ratio", value: kpi.sharpe == null ? "—" : kpi.sharpe.toFixed(2), delta: delta(kpi.sharpe, base.sharpe), text: "", good: true },
    { label: "Max drawdown (hist.)", value: pctFraction(kpi.maxDrawdown, 1), delta: delta(kpi.maxDrawdown, base.maxDrawdown), text: "", good: true },
    { label: `Beta (vs ${typeof quant?.benchmark?.symbol === "string" ? quant.benchmark.symbol : "benchmark"})`, value: kpi.beta == null ? "—" : kpi.beta.toFixed(2), delta: delta(kpi.beta, base.beta), text: "", good: null },
  ];
  const unavailableNote = (label: string) => {
    if (label.startsWith("Sharpe") && kpi.sharpe == null) return rf == null ? "Needs observed risk-free rate" : "";
    if (label.startsWith("Max") && kpi.maxDrawdown == null) return comparing ? "Current only" : "History unavailable";
    if (label.startsWith("Beta") && kpi.beta == null) return comparing ? "Current only" : quant?.benchmark?.available === false ? "Benchmark unavailable" : "";
    return "";
  };

  if (loading) return <div className={s.skeleton} aria-busy="true" />;
  const quantFailed = !data.quant && resources.quant.status === "error";
  const needsQuant = tab === "correlation" || tab === "contribution";
  const view = (() => {
    switch (tab) {
      case "frontier": return <Gate resource={resources.frontier} label="Efficient frontier">{value => <FrontierView frontier={value} assumptions={assumptions} points={visible} showAssets={showAssets} chartRef={chartRef} />}</Gate>;
      case "capm": return <Gate resource={resources.capm} label="CAPM / SML">{value => <CapmView capm={value} chartRef={chartRef} />}</Gate>;
      case "rolling": return <Gate resource={resources.rolling} label="Rolling risk">{value => <RollingView rolling={value} chartRef={chartRef} />}</Gate>;
      case "distribution": return <Gate resource={resources.distribution} label="Return distribution">{value => <DistributionView distribution={value} chartRef={chartRef} />}</Gate>;
      default:
        if (needsQuant && !quant) return quantFailed
          ? <Unavailable title="Quant analysis request failed" text={resources.quant.error ?? "The model did not respond."} onRetry={resources.quant.retry} />
          : <div className={s.skeleton} aria-busy="true" />;
        return tab === "correlation" ? <CorrelationView quant={quant} chartRef={chartRef} /> : <ContributionView quant={quant} budget={data.riskBudget} chartRef={chartRef} />;
    }
  })();

  return <div className={s.layout}>
    <div className={s.main}>
      <div className={s.subtabs} role="tablist" aria-label="Quant analyses">
        {quantTabs.map(item => <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}
      </div>
      <div className={s.chartBox}>{view}</div>
      {quant?.warnings.length ? <Notes items={quant.warnings} /> : null}
      <dl className={s.kpis} aria-label={comparing ? `${focus?.label} compared with current portfolio` : "Current portfolio statistics"}>
        {kpis.map(item => {
          const note = unavailableNote(item.label);
          const showDelta = comparing && item.delta != null;
          return <div className={s.kpi} key={item.label}>
            <dt>{item.label}</dt>
            <dd>
              <span className={s.kpiValue}>{item.value}</span>
              <span className={`${s.kpiDelta} ${showDelta && item.good != null ? tone(item.delta, item.good) : ""}`}>
                {showDelta ? `${item.label.startsWith("Sharpe") || item.label.startsWith("Beta") ? signedNumber(item.delta) : `${(item.delta as number) > 0 ? "+" : ""}${((item.delta as number) * 100).toFixed(1)} pp`} vs current` : note || (comparing ? "" : "Current portfolio")}
              </span>
            </dd>
          </div>;
        })}
      </dl>
      <p className={s.basis}>
        {comparing ? `Showing ${focus?.label} against the current portfolio. ` : ""}
        Return, volatility and Sharpe use the risky-sleeve estimator ({assumptions ? `data to ${assumptions.data_cutoff}` : "date unavailable"}); drawdown and beta come from the ledger history and exist only for the current portfolio. Historical estimates are a modeling lens, not a forecast.
      </p>
    </div>
    <QuantRail onRetryAssumptions={resources.assumptions.status === "error" ? resources.assumptions.retry : undefined} assumptions={assumptions} frontier={frontier} points={points} checked={checked}
      onToggle={id => setOverrides(current => ({ ...current, [id]: !checked[id] }))}
      showAssets={showAssets} onToggleAssets={() => setShowAssets(value => !value)} assetsAvailable={assetsAvailable}
      canPng={Boolean(rows)} canCsv={Boolean(rows)} onPng={png} onCsv={csv} />
  </div>;
}
