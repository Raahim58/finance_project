"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Portfolio, getPortfolios } from "@/lib/api";

const tabs = ["overview", "build", "quant", "risk", "stress", "research", "activity", "settings"] as const;

export function PortfolioWorkspace({ portfolioId, active, children }: { portfolioId: string; active: string; children: React.ReactNode }) {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  useEffect(() => { void getPortfolios().then(setPortfolios); }, []);
  return (
    <section className="mx-auto grid max-w-7xl gap-5 px-5 py-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="text-xs uppercase tracking-wider text-muted">Portfolio workspace</p><h1 className="text-2xl font-semibold text-ink">{portfolios.find((item) => item.id === portfolioId)?.name ?? "Portfolio"}</h1></div>
        <select className="rounded-md border border-line bg-white px-3 py-2 text-sm" value={portfolioId} onChange={(event) => { window.location.href = `/portfolios/${event.target.value}/${active}`; }}>
          {portfolios.map((portfolio) => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}
        </select>
      </div>
      <nav className="flex gap-2 overflow-x-auto rounded-lg border border-line bg-white p-2 text-sm">
        {tabs.map((tab) => <Link key={tab} href={`/portfolios/${portfolioId}/${tab}`} className={`rounded-md px-3 py-2 capitalize ${active === tab ? "bg-accent text-white" : "text-muted hover:bg-surface"}`}>{tab}</Link>)}
      </nav>
      {children}
    </section>
  );
}
