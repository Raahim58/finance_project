"use client";

import { useEffect, useState } from "react";
import {
  getAlerts, getIpsCompliance, getMacroRegime, getMarketFreshness, getMarketOverview,
  getPortfolioPerformance, getPortfolioSummary, getPortfolios,
  type Compliance, type MacroRegime, type MarketFreshness, type MarketOverview,
  type Portfolio, type PortfolioPerformancePoint, type PortfolioSummary,
} from "@/lib/api";
import { request } from "@/lib/api/client";
import { getEventFeed, getPortfolioEventIntelligence, type PortfolioEventIntelligence, type ResearchEventView } from "@/lib/api/research";

export type Resource<T> = { status: "loading" | "ready" | "error"; data: T | null; error?: string };
export type OverviewUser = { full_name: string | null; email: string };
const loading = <T,>(): Resource<T> => ({ status: "loading", data: null });
const empty = <T,>(): Resource<T> => ({ status: "ready", data: null });

export function useOverviewData() {
  const [revision, setRevision] = useState(0);
  const [portfolioId, setPortfolioId] = useState("");
  const [portfolios, setPortfolios] = useState<Resource<Portfolio[]>>(loading);
  const [market, setMarket] = useState<Resource<MarketOverview>>(loading);
  const [freshness, setFreshness] = useState<Resource<MarketFreshness>>(loading);
  const [events, setEvents] = useState<Resource<ResearchEventView[]>>(loading);
  const [regime, setRegime] = useState<Resource<MacroRegime>>(loading);
  const [user, setUser] = useState<Resource<OverviewUser>>(loading);
  const [scope, setScope] = useState({
    id: "", summary: empty<PortfolioSummary>(), performance: empty<PortfolioPerformancePoint[]>(),
    alerts: empty<Array<Record<string, unknown>>>(), compliance: empty<Compliance>(), exposure: empty<PortfolioEventIntelligence>(),
  });

  useEffect(() => {
    let active = true;
    const read = async <T,>(fetcher: () => Promise<T>, setter: (value: Resource<T>) => void) => {
      setter(loading<T>());
      try { const data = await fetcher(); if (active) setter({ status: "ready", data }); }
      catch (error) { if (active) setter({ status: "error", data: null, error: error instanceof Error ? error.message : "Request failed" }); }
    };
    // Independent reads: a slow portfolio or research service cannot block the market.
    void read(getMarketOverview, setMarket);
    void read(getMarketFreshness, setFreshness);
    void read(async () => (await getEventFeed()).events, setEvents);
    void read(getMacroRegime, setRegime);
    void read(() => request<OverviewUser>("/auth/me"), setUser);
    void read(async () => {
      const rows = (await getPortfolios()).filter(row => !row.archived_at);
      if (active) setPortfolioId(current => rows.some(row => row.id === current) ? current : rows.find(row => row.is_default)?.id ?? "");
      return rows;
    }, setPortfolios);
    return () => { active = false; };
  }, [revision]);

  useEffect(() => {
    let active = true;
    const initial = { id: portfolioId, summary: empty<PortfolioSummary>(), performance: empty<PortfolioPerformancePoint[]>(),
      alerts: empty<Array<Record<string, unknown>>>(), compliance: empty<Compliance>(), exposure: empty<PortfolioEventIntelligence>() };
    if (!portfolioId) { setScope(initial); return; }
    setScope({ ...initial, summary: loading(), performance: loading(), alerts: loading(), compliance: loading(), exposure: loading() });
    const read = async <T,>(key: "summary" | "performance" | "alerts" | "compliance" | "exposure", fetcher: () => Promise<T>) => {
      try { const data = await fetcher(); if (active) setScope(current => ({ ...current, [key]: { status: "ready", data } })); }
      catch (error) { if (active) setScope(current => ({ ...current, [key]: { status: "error", data: null, error: error instanceof Error ? error.message : "Request failed" } })); }
    };
    void read("summary", () => getPortfolioSummary(portfolioId));
    void read("performance", () => getPortfolioPerformance(portfolioId, 500));
    void read("alerts", () => getAlerts(portfolioId, "active"));
    void read("compliance", () => getIpsCompliance(portfolioId));
    void read("exposure", () => getPortfolioEventIntelligence(portfolioId, 5));
    return () => { active = false; };
  }, [portfolioId, revision]);

  const selectedScope = scope.id === portfolioId ? scope : {
    id: portfolioId, summary: loading<PortfolioSummary>(), performance: loading<PortfolioPerformancePoint[]>(),
    alerts: loading<Array<Record<string, unknown>>>(), compliance: loading<Compliance>(), exposure: loading<PortfolioEventIntelligence>(),
  };
  return { portfolios, portfolioId, setPortfolioId, market, freshness, events, regime, user, ...selectedScope, reload: () => setRevision(value => value + 1) };
}
