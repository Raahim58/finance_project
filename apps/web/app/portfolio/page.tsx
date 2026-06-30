"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  Portfolio,
  PortfolioExposure,
  PortfolioRiskFlags,
  PortfolioSummary,
  addHolding,
  createPortfolio,
  getPortfolioExposure,
  getPortfolioRiskFlags,
  getPortfolioSummary,
  getPortfolios
} from "@/lib/api";

function formatMoney(value: string | number | null | undefined) {
  const numeric = Number(value ?? 0);
  return `PKR ${new Intl.NumberFormat("en-PK", { maximumFractionDigits: 0 }).format(numeric)}`;
}

function formatPercent(value: string | number | null | undefined) {
  if (value === null || value === undefined) return "n/a";
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

function toneClass(value: string | number | null | undefined) {
  const numeric = Number(value ?? 0);
  if (numeric > 0) return "text-accent";
  if (numeric < 0) return "text-warn";
  return "text-muted";
}

export default function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [exposure, setExposure] = useState<PortfolioExposure | null>(null);
  const [riskFlags, setRiskFlags] = useState<PortfolioRiskFlags | null>(null);
  const [portfolioName, setPortfolioName] = useState("Main portfolio");
  const [symbol, setSymbol] = useState("MEBL");
  const [quantity, setQuantity] = useState("10");
  const [averageCost, setAverageCost] = useState("200");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadPortfolios() {
    const rows = await getPortfolios();
    setPortfolios(rows);
    const nextSelected = selectedId || rows[0]?.id || "";
    setSelectedId(nextSelected);
    return nextSelected;
  }

  async function loadPortfolioData(portfolioId: string) {
    if (!portfolioId) {
      setSummary(null);
      setExposure(null);
      setRiskFlags(null);
      return;
    }
    const [nextSummary, nextExposure, nextRiskFlags] = await Promise.all([
      getPortfolioSummary(portfolioId),
      getPortfolioExposure(portfolioId),
      getPortfolioRiskFlags(portfolioId)
    ]);
    setSummary(nextSummary);
    setExposure(nextExposure);
    setRiskFlags(nextRiskFlags);
  }

  useEffect(() => {
    void loadPortfolios()
      .then(loadPortfolioData)
      .catch((error: Error) => setMessage(error.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void loadPortfolioData(selectedId).catch((error: Error) => setMessage(error.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  async function onCreatePortfolio(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      const created = await createPortfolio(portfolioName);
      setPortfolios([...portfolios, created]);
      setSelectedId(created.id);
      setMessage("Portfolio created.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not create portfolio");
    }
  }

  async function onAddHolding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedId) return;
    setMessage(null);
    try {
      await addHolding(selectedId, symbol.toUpperCase(), quantity, averageCost);
      await loadPortfolioData(selectedId);
      setMessage("Holding saved. Existing symbols are updated in place.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save holding");
    }
  }

  if (loading) {
    return <section className="mx-auto max-w-6xl px-5 py-8 text-sm text-muted">Loading portfolio...</section>;
  }

  return (
    <section className="mx-auto grid max-w-6xl gap-6 px-5 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Portfolio</h1>
          <p className="mt-2 text-sm text-muted">
            Phase 3 portfolio valuation uses stored holdings and the latest market prices in the database.
          </p>
        </div>
        {portfolios.length ? (
          <select
            className="rounded-md border border-line bg-white px-3 py-2 text-sm"
            value={selectedId}
            onChange={(event) => setSelectedId(event.target.value)}
          >
            {portfolios.map((portfolio) => (
              <option key={portfolio.id} value={portfolio.id}>
                {portfolio.name}
              </option>
            ))}
          </select>
        ) : null}
      </div>

      {message ? <p className="rounded-md border border-line bg-white px-4 py-3 text-sm text-ink">{message}</p> : null}

      <div className="grid gap-4 lg:grid-cols-[0.85fr_1.15fr]">
        <form onSubmit={onCreatePortfolio} className="grid content-start gap-4 rounded-lg border border-line bg-white p-5">
          <h2 className="text-base font-semibold text-ink">Create portfolio</h2>
          <label className="grid gap-2 text-sm text-ink">
            Name
            <input
              className="rounded-md border border-line px-3 py-2"
              value={portfolioName}
              onChange={(event) => setPortfolioName(event.target.value)}
              required
            />
          </label>
          <button className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white" type="submit">
            Create
          </button>
        </form>

        <form onSubmit={onAddHolding} className="grid gap-4 rounded-lg border border-line bg-white p-5 md:grid-cols-4">
          <h2 className="text-base font-semibold text-ink md:col-span-4">Add or update holding</h2>
          <label className="grid gap-2 text-sm text-ink">
            Symbol
            <input
              className="rounded-md border border-line px-3 py-2 uppercase"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              required
            />
          </label>
          <label className="grid gap-2 text-sm text-ink">
            Quantity
            <input
              className="rounded-md border border-line px-3 py-2"
              inputMode="decimal"
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              required
            />
          </label>
          <label className="grid gap-2 text-sm text-ink">
            Average cost
            <input
              className="rounded-md border border-line px-3 py-2"
              inputMode="decimal"
              value={averageCost}
              onChange={(event) => setAverageCost(event.target.value)}
              required
            />
          </label>
          <button
            className="self-end rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
            type="submit"
            disabled={!selectedId}
          >
            Save holding
          </button>
        </form>
      </div>

      {summary ? (
        <>
          <div className="grid gap-4 md:grid-cols-4">
            {[
              ["Value", formatMoney(summary.total_value)],
              ["Cost", formatMoney(summary.cost_basis)],
              ["Unrealized PnL", formatMoney(summary.unrealized_gain_loss)],
              ["Day change", formatMoney(summary.day_change)]
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-line bg-white p-4">
                <p className="text-xs uppercase text-muted">{label}</p>
                <p className="mt-2 text-xl font-semibold text-ink">{value}</p>
              </div>
            ))}
          </div>

          <p className="text-sm text-muted">
            Freshness: {summary.data_freshness_date ?? "missing"} · Source: {summary.data_source ?? "missing"}
          </p>

          <section className="rounded-lg border border-line bg-white">
            <div className="border-b border-line px-4 py-3">
              <h2 className="text-sm font-semibold text-ink">Holdings</h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="bg-surface text-xs uppercase text-muted">
                  <tr>
                    <th className="px-4 py-3">Symbol</th>
                    <th className="px-4 py-3">Qty</th>
                    <th className="px-4 py-3">Avg cost</th>
                    <th className="px-4 py-3">Price</th>
                    <th className="px-4 py-3">Value</th>
                    <th className="px-4 py-3">PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.holdings.map((holding) => (
                    <tr key={holding.holding_id} className="border-t border-line">
                      <td className="px-4 py-3">
                        <a className="font-semibold text-accent" href={`/companies/${holding.symbol}`}>
                          {holding.symbol}
                        </a>
                        <p className="text-xs text-muted">{holding.sector}</p>
                      </td>
                      <td className="px-4 py-3 text-ink">{Number(holding.quantity).toLocaleString("en-PK")}</td>
                      <td className="px-4 py-3 text-muted">{formatMoney(holding.average_cost)}</td>
                      <td className="px-4 py-3 text-muted">{formatMoney(holding.latest_price)}</td>
                      <td className="px-4 py-3 text-ink">{formatMoney(holding.market_value)}</td>
                      <td className={`px-4 py-3 font-medium ${toneClass(holding.unrealized_gain_loss)}`}>
                        {formatMoney(holding.unrealized_gain_loss)}
                        <p className="text-xs">{formatPercent(holding.unrealized_gain_loss_percent)}</p>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <p className="rounded-md border border-line bg-white px-4 py-3 text-sm text-muted">
          Create a portfolio and add holdings to see valuation, exposure, and PnL.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold text-ink">Sector exposure</h2>
          </div>
          <div className="grid gap-2 p-4">
            {(exposure?.by_sector ?? []).map((row) => (
              <div key={row.sector} className="grid grid-cols-[1fr_auto] gap-3 rounded-md border border-line bg-surface px-3 py-2 text-sm">
                <span className="font-medium text-ink">{row.sector}</span>
                <span className="text-muted">{formatPercent(row.weight_percent)}</span>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-line bg-white">
          <div className="border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold text-ink">Risk flags</h2>
          </div>
          <div className="grid gap-2 p-4">
            {(riskFlags?.flags.length ? riskFlags.flags : [{ code: "none", severity: "info", message: "No risk flags for current holdings." }]).map((flag) => (
              <div key={`${flag.code}-${flag.message}`} className="rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink">
                <span className="mr-2 text-xs uppercase text-muted">{flag.severity}</span>
                {flag.message}
              </div>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
