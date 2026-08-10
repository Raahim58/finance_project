"use client";

import { FormEvent, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { EvidenceBadge } from "@/components/EvidenceBadge";
import { PortfolioWorkspace } from "@/components/PortfolioWorkspace";
import { QuantChart } from "@/components/QuantChart";
import { createAllocation, createIpsVersion, getAlerts, getIpsCompliance, getPortfolioQuant, getPortfolioSummary, getRecommendations, PortfolioQuant, PortfolioSummary, runScenario, searchRag } from "@/lib/api";

export function WorkspacePage({ mode }: { mode: string }) {
  const params = useParams<{ portfolioId: string }>();
  const portfolioId = params.portfolioId;
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [quant, setQuant] = useState<PortfolioQuant | null>(null);
  const [data, setData] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => { void getPortfolioSummary(portfolioId).then(setSummary).catch((error: Error) => setMessage(error.message)); if (["quant", "risk"].includes(mode)) void getPortfolioQuant(portfolioId).then(setQuant).catch((error: Error) => setMessage(error.message)); if (mode === "settings") void getIpsCompliance(portfolioId).then(setData); if (mode === "activity") void Promise.all([getAlerts(portfolioId), getRecommendations()]).then(([alerts, recommendations]) => setData({ alerts, recommendations })); }, [portfolioId, mode]);

  async function build(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget); const symbol = String(form.get("symbol") || "").toUpperCase(); const weight = Number(form.get("weight"));
    try { setData(await createAllocation(portfolioId, { kind: "sandbox", items: [{ symbol, target_weight: weight, locked: false, is_cash: false }, { symbol: "CASH", target_weight: 1 - weight, locked: false, is_cash: true }], base_value: Number(summary?.total_value ?? 0), assumptions: { source: "workspace_draft" } })); setMessage("Sandbox allocation saved."); } catch (error) { setMessage(error instanceof Error ? error.message : "Could not save allocation"); }
  }

  async function stress(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    try { setData(await runScenario(portfolioId, { name: String(form.get("name")), shocks: { [String(form.get("symbol")).toUpperCase()]: Number(form.get("shock")) }, sector_shocks: {}, factor_shocks: {} })); } catch (error) { setMessage(error instanceof Error ? error.message : "Could not run scenario"); }
  }

  async function research(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const query = String(new FormData(event.currentTarget).get("query")); setData(await searchRag({ query, limit: 8, portfolio_id: portfolioId } as Parameters<typeof searchRag>[0]));
  }

  async function ips(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    setData(await createIpsVersion(portfolioId, { constraints: { long_only: true, max_instrument_weight: Number(form.get("maxWeight")), min_cash_weight: Number(form.get("minCash")) }, starting_capital: Number(form.get("capital")), target_value: Number(form.get("target")), horizon_years: Number(form.get("years")), goal: String(form.get("goal")) }, true));
  }

  return <PortfolioWorkspace portfolioId={portfolioId} active={mode}>
    {message ? <p className="rounded-md border border-line bg-white px-4 py-3 text-sm">{message}</p> : null}
    {summary ? <EvidenceBadge asOf={summary.data_freshness_date} source={summary.data_source} warning={!summary.portfolio.history_complete ? "History before the opening-balance baseline is unavailable." : null} /> : null}
    {mode === "overview" && summary ? <><div className="grid gap-4 md:grid-cols-4">{[["Value", summary.total_value], ["Cash", summary.cash_balance], ["PnL", summary.unrealized_gain_loss], ["Holdings", summary.holdings.length]].map(([label, value]) => <div key={label} className="rounded-lg border border-line bg-white p-5"><p className="text-xs uppercase text-muted">{label}</p><p className="mt-2 text-xl font-semibold">{String(value)}</p></div>)}</div><QuantChart title="Capital by holding" labels={summary.holdings.map((item) => item.symbol)} values={summary.holdings.map((item) => Number(item.market_value))} /></> : null}
    {mode === "build" ? <form onSubmit={build} className="grid gap-4 rounded-lg border border-line bg-white p-5 md:grid-cols-3"><h2 className="md:col-span-3 font-semibold">Sandbox allocation</h2><input name="symbol" placeholder="PSX symbol" className="rounded-md border border-line px-3 py-2" required /><input name="weight" type="number" min="0" max="1" step="0.01" defaultValue="0.6" className="rounded-md border border-line px-3 py-2" /><button className="rounded-md bg-accent px-4 py-2 text-white">Save sandbox</button></form> : null}
    {mode === "quant" && quant ? <><div className="grid gap-4 md:grid-cols-3">{Object.entries(quant.portfolio).slice(0, 9).map(([key, value]) => <div key={key} className="rounded-lg border border-line bg-white p-4"><p className="text-xs uppercase text-muted">{key.replaceAll("_", " ")}</p><p className="mt-2 font-semibold">{String(value)}</p></div>)}</div><QuantChart title="Percentage risk contribution" labels={Object.keys(quant.risk_contributions)} values={Object.values(quant.risk_contributions)} /></> : null}
    {mode === "risk" && quant ? <><QuantChart title="Risk contribution" labels={Object.keys(quant.risk_contributions)} values={Object.values(quant.risk_contributions)} /><pre className="overflow-auto rounded-lg border border-line bg-white p-4 text-xs">{JSON.stringify({ warnings: quant.warnings, covariance: quant.covariance, correlation: quant.correlation }, null, 2)}</pre></> : null}
    {mode === "stress" ? <><form onSubmit={stress} className="grid gap-4 rounded-lg border border-line bg-white p-5 md:grid-cols-4"><input name="name" defaultValue="Equity shock" className="rounded-md border border-line px-3 py-2" /><input name="symbol" placeholder="MEBL" className="rounded-md border border-line px-3 py-2" required /><input name="shock" type="number" step="0.01" defaultValue="-0.1" className="rounded-md border border-line px-3 py-2" /><button className="rounded-md bg-accent px-4 py-2 text-white">Run stress</button></form><Result data={data} /></> : null}
    {mode === "research" ? <><form onSubmit={research} className="flex gap-3 rounded-lg border border-line bg-white p-5"><input name="query" placeholder="Search portfolio documents" className="flex-1 rounded-md border border-line px-3 py-2" required /><button className="rounded-md bg-accent px-4 py-2 text-white">Search</button></form><Result data={data} /></> : null}
    {mode === "activity" ? <Result data={data} /> : null}
    {mode === "settings" ? <><form onSubmit={ips} className="grid gap-4 rounded-lg border border-line bg-white p-5 md:grid-cols-3"><h2 className="md:col-span-3 font-semibold">Confirm investment policy</h2><input name="goal" placeholder="Goal" className="rounded-md border border-line px-3 py-2" /><input name="capital" type="number" placeholder="Starting capital" className="rounded-md border border-line px-3 py-2" required /><input name="target" type="number" placeholder="Target value" className="rounded-md border border-line px-3 py-2" required /><input name="years" type="number" defaultValue="5" className="rounded-md border border-line px-3 py-2" /><input name="maxWeight" type="number" step="0.01" defaultValue="0.3" className="rounded-md border border-line px-3 py-2" /><input name="minCash" type="number" step="0.01" defaultValue="0.05" className="rounded-md border border-line px-3 py-2" /><button className="rounded-md bg-accent px-4 py-2 text-white">Confirm IPS</button></form><Result data={data} /></> : null}
  </PortfolioWorkspace>;
}

function Result({ data }: { data: unknown }) { return data ? <pre className="max-h-[520px] overflow-auto rounded-lg border border-line bg-white p-4 text-xs leading-5">{JSON.stringify(data, null, 2)}</pre> : null; }
