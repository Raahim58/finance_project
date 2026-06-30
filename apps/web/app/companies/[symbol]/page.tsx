"use client";

import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { CompanyDetail, MarketPrice, getCompanyDetail, getCompanyHistory } from "@/lib/api";

function formatNumber(value: number | string, maximumFractionDigits = 2) {
  const numeric = typeof value === "string" ? Number(value) : value;
  return new Intl.NumberFormat("en-PK", { maximumFractionDigits }).format(numeric);
}

function formatPercent(value: string) {
  const numeric = Number(value);
  const sign = numeric > 0 ? "+" : "";
  return `${sign}${numeric.toFixed(2)}%`;
}

function PriceChart({ rows }: { rows: MarketPrice[] }) {
  const path = useMemo(() => {
    if (rows.length < 2) return "";
    const closes = rows.map((row) => Number(row.close));
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const span = Math.max(max - min, 1);
    return closes
      .map((close, index) => {
        const x = (index / (closes.length - 1)) * 100;
        const y = 90 - ((close - min) / span) * 80;
        return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
      })
      .join(" ");
  }, [rows]);

  if (!path) {
    return <div className="grid h-64 place-items-center text-sm text-muted">Not enough history to chart.</div>;
  }

  return (
    <svg className="h-64 w-full" viewBox="0 0 100 100" preserveAspectRatio="none" role="img">
      <line x1="0" x2="100" y1="90" y2="90" stroke="#d7dde2" strokeWidth="0.5" />
      <line x1="0" x2="100" y1="50" y2="50" stroke="#d7dde2" strokeWidth="0.35" />
      <line x1="0" x2="100" y1="10" y2="10" stroke="#d7dde2" strokeWidth="0.5" />
      <path d={path} fill="none" stroke="#0f766e" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
    </svg>
  );
}

export default function CompanyPage() {
  const params = useParams<{ symbol: string }>();
  const symbol = params.symbol?.toUpperCase() ?? "";
  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [history, setHistory] = useState<MarketPrice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!symbol) return;
    void Promise.all([getCompanyDetail(symbol), getCompanyHistory(symbol, 180)])
      .then(([companyDetail, companyHistory]) => {
        setDetail(companyDetail);
        setHistory(companyHistory);
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading) {
    return <section className="mx-auto max-w-6xl px-5 py-8 text-sm text-muted">Loading company...</section>;
  }

  if (error || !detail) {
    return (
      <section className="mx-auto grid max-w-6xl gap-4 px-5 py-8">
        <h1 className="text-2xl font-semibold text-ink">{symbol}</h1>
        <p className="rounded-md border border-line bg-white px-4 py-3 text-sm text-warn">
          {error ?? "Company not found"}
        </p>
      </section>
    );
  }

  const latest = detail.latest_price;

  return (
    <section className="mx-auto grid max-w-6xl gap-6 px-5 py-8">
      <div>
        <a className="text-sm text-accent" href="/market">
          Market
        </a>
        <h1 className="mt-2 text-3xl font-semibold text-ink">{detail.company.symbol}</h1>
        <p className="mt-1 text-sm text-muted">
          {detail.company.name} · {detail.company.sector} · {detail.company.exchange.code}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {[
          ["Close", latest ? `PKR ${formatNumber(latest.close)}` : "Missing"],
          ["Change", latest ? formatPercent(latest.change_percent) : "Missing"],
          ["Volume", latest ? formatNumber(latest.volume, 0) : "Missing"],
          ["Date", latest?.trade_date ?? "Missing"]
        ].map(([label, value]) => (
          <div key={label} className="rounded-lg border border-line bg-white p-4">
            <p className="text-xs uppercase text-muted">{label}</p>
            <p className="mt-2 text-xl font-semibold text-ink">{value}</p>
          </div>
        ))}
      </div>

      <section className="rounded-lg border border-line bg-white p-4">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-ink">Price history</h2>
          <p className="text-xs text-muted">Source: {latest?.source ?? "unknown"}</p>
        </div>
        <PriceChart rows={history} />
      </section>

      <section className="rounded-lg border border-line bg-white">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Recent prices</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface text-xs uppercase text-muted">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Open</th>
                <th className="px-4 py-3">High</th>
                <th className="px-4 py-3">Low</th>
                <th className="px-4 py-3">Close</th>
                <th className="px-4 py-3">Volume</th>
              </tr>
            </thead>
            <tbody>
              {history.slice(-12).reverse().map((row) => (
                <tr key={row.trade_date} className="border-t border-line">
                  <td className="px-4 py-3 text-ink">{row.trade_date}</td>
                  <td className="px-4 py-3 text-muted">{formatNumber(row.open)}</td>
                  <td className="px-4 py-3 text-muted">{formatNumber(row.high)}</td>
                  <td className="px-4 py-3 text-muted">{formatNumber(row.low)}</td>
                  <td className="px-4 py-3 font-medium text-ink">{formatNumber(row.close)}</td>
                  <td className="px-4 py-3 text-muted">{formatNumber(row.volume, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
