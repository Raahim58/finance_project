"use client";

import { useEffect, useState } from "react";

import {
  Company,
  MarketFreshness,
  MarketOverview,
  MarketPrice,
  getCompanies,
  getMarketFreshness,
  getMarketOverview
} from "@/lib/api";

function formatNumber(value: number | string, maximumFractionDigits = 2) {
  const numeric = typeof value === "string" ? Number(value) : value;
  return new Intl.NumberFormat("en-PK", { maximumFractionDigits }).format(numeric);
}

function formatPercent(value: string) {
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

function changeClass(value: string) {
  const numeric = Number(value);
  if (numeric > 0) return "text-accent";
  if (numeric < 0) return "text-warn";
  return "text-muted";
}

function PriceTable({ title, rows }: { title: string; rows: MarketPrice[] }) {
  return (
    <section className="rounded-lg border border-line bg-white">
      <div className="border-b border-line px-4 py-3">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="bg-surface text-xs uppercase text-muted">
            <tr>
              <th className="px-4 py-3">Symbol</th>
              <th className="px-4 py-3">Close</th>
              <th className="px-4 py-3">Change</th>
              <th className="px-4 py-3">Volume</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${title}-${row.symbol}`} className="border-t border-line">
                <td className="px-4 py-3 font-semibold text-ink">
                  <a href={`/companies/${row.symbol}`} className="text-accent">
                    {row.symbol}
                  </a>
                </td>
                <td className="px-4 py-3 text-ink">{formatNumber(row.close)}</td>
                <td className={`px-4 py-3 font-medium ${changeClass(row.change_percent)}`}>
                  {formatPercent(row.change_percent)}
                </td>
                <td className="px-4 py-3 text-muted">{formatNumber(row.volume, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default function MarketPage() {
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [freshness, setFreshness] = useState<MarketFreshness | null>(null);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void Promise.all([getMarketOverview(), getMarketFreshness(), getCompanies()])
      .then(([marketOverview, marketFreshness, companyRows]) => {
        setOverview(marketOverview);
        setFreshness(marketFreshness);
        setCompanies(companyRows);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void getCompanies(query)
        .then(setCompanies)
        .catch((err: Error) => setError(err.message));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  if (loading) {
    return <section className="mx-auto max-w-6xl px-5 py-8 text-sm text-muted">Loading market data...</section>;
  }

  if (error) {
    return (
      <section className="mx-auto grid max-w-6xl gap-4 px-5 py-8">
        <h1 className="text-2xl font-semibold text-ink">Market</h1>
        <p className="rounded-md border border-line bg-white px-4 py-3 text-sm text-warn">{error}</p>
        <p className="text-sm text-muted">Run `python -m app.jobs.scheduler --once` in `apps/api` after setting `MARKET_DATA_MODE`.</p>
      </section>
    );
  }

  return (
    <section className="mx-auto grid max-w-6xl gap-6 px-5 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-ink">Market</h1>
          <p className="mt-2 text-sm text-muted">
            Data mode: {freshness?.market_data_mode ?? "unknown"}.
            {" "}Latest trade date: {freshness?.latest_trade_date ?? "not available"}.
            {" "}Last updated: {freshness?.last_successful_ingestion_at ?? "not available"}.
          </p>
        </div>
        <input
          className="w-full max-w-xs rounded-md border border-line bg-white px-3 py-2 text-sm"
          placeholder="Search company"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {freshness?.stale_warning ? (
        <p className="rounded-md border border-line bg-white px-4 py-3 text-sm text-warn">
          {freshness.stale_warning}
        </p>
      ) : null}

      {overview?.snapshot ? (
        <div className="grid gap-4 md:grid-cols-4">
          {[
            ["Index", overview.snapshot.index_name],
            ["Value", formatNumber(overview.snapshot.index_value)],
            ["Change", formatPercent(overview.snapshot.index_change_percent)],
            ["Volume", formatNumber(overview.snapshot.total_volume, 0)]
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-line bg-white p-4">
              <p className="text-xs uppercase text-muted">{label}</p>
              <p className="mt-2 text-xl font-semibold text-ink">{value}</p>
            </div>
          ))}
        </div>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-3">
        <PriceTable title="Top gainers" rows={overview?.top_gainers ?? []} />
        <PriceTable title="Top losers" rows={overview?.top_losers ?? []} />
        <PriceTable title="Volume leaders" rows={overview?.top_volume ?? []} />
      </div>

      <section className="rounded-lg border border-line bg-white">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Sector performance</h2>
        </div>
        <div className="grid gap-2 p-4 md:grid-cols-2">
          {(overview?.sectors ?? []).map((sector) => (
            <a
              key={sector.sector}
              href={`/market?sector=${encodeURIComponent(sector.sector)}`}
              className="grid grid-cols-[1fr_auto] items-center rounded-md border border-line bg-surface px-3 py-2 text-sm"
            >
              <span className="font-medium text-ink">{sector.sector}</span>
              <span className={changeClass(sector.average_change_percent)}>
                {formatPercent(sector.average_change_percent)}
              </span>
            </a>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-line bg-white">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Companies</h2>
        </div>
        <div className="grid gap-2 p-4 md:grid-cols-2 lg:grid-cols-3">
          {companies.map((company) => (
            <a
              key={company.symbol}
              href={`/companies/${company.symbol}`}
              className="rounded-md border border-line bg-surface px-3 py-3 text-sm"
            >
              <span className="font-semibold text-accent">{company.symbol}</span>
              <span className="ml-2 text-ink">{company.name}</span>
              <p className="mt-1 text-xs text-muted">{company.sector}</p>
            </a>
          ))}
        </div>
      </section>
    </section>
  );
}
