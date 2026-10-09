"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export const PORTFOLIO_TABS: Array<[string, string]> = [["overview", "Overview"], ["ips", "IPS"], ["build", "Build"], ["quant", "Quant"], ["risk", "Risk"], ["scenarios", "Scenarios"], ["research", "Research"], ["activity", "Activity"]];

/** Route match for /portfolios/{id}/{tab}; null elsewhere (e.g. /portfolios/manage). */
export function portfolioRoute(pathname: string) {
  const match = pathname.match(/^\/portfolios\/([^/]+)\/([^/]+)/);
  return match && match[1] !== "manage" ? { id: match[1], tab: match[2] === "stress" ? "scenarios" : match[2] === "settings" ? "ips" : match[2] } : null;
}

export function PortfolioTabs() {
  const route = portfolioRoute(usePathname());
  if (!route) return null;
  return (
    <nav aria-label="Portfolio sections" className="ptabs">
      {PORTFOLIO_TABS.map(([slug, label]) => (
        <Link key={slug} href={`/portfolios/${route.id}/${slug}` as never} aria-current={route.tab === slug ? "page" : undefined}>{label}</Link>
      ))}
    </nav>
  );
}
