"use client";

import { useEffect, useState } from "react";
import { getCompanyTrends, getCompanies, getIndexHistory, getMarketFreshness, getMarketOverview, type Company, type IndexClose, type MarketFreshness, type MarketOverview } from "@/lib/api";
import { getEventFeed, type ResearchEventView } from "@/lib/api/research";
import type { Resource } from "@/components/overview/useOverviewData";

const loading = <T,>(): Resource<T> => ({ status: "loading", data: null });

const INDEX_SYMBOL = "KSE-100";

export function useMarketsData() {
  const [trends, setTrends] = useState<Record<string, number[]>>({});
  const [revision, setRevision] = useState(0);
  const [market, setMarket] = useState<Resource<MarketOverview>>(loading);
  const [freshness, setFreshness] = useState<Resource<MarketFreshness>>(loading);
  const [companies, setCompanies] = useState<Resource<Company[]>>(loading);
  const [events, setEvents] = useState<Resource<ResearchEventView[]>>(loading);
  const [history, setHistory] = useState<Resource<IndexClose[]>>(loading);

  useEffect(() => {
    let active = true;
    let refreshing = false;
    const read = async <T,>(fetcher: () => Promise<T>, setter: (value: Resource<T>) => void) => {
      setter(loading<T>());
      try { const data = await fetcher(); if (active) setter({ status: "ready", data }); return data; }
      catch (error) { if (active) setter({ status: "error", data: null, error: error instanceof Error ? error.message : "Request failed" }); return null; }
    };
    void read(() => getCompanies(), setCompanies);
    void read(getMarketFreshness, setFreshness);
    void read(async () => (await getEventFeed()).events, setEvents);
    const readTrends = async (snapshot: MarketOverview | null) => {
      if (!snapshot) return;
      const symbols = Array.from(new Set([...snapshot.top_gainers, ...snapshot.top_losers, ...snapshot.top_volume].map(row => row.symbol)));
      try { const values = await getCompanyTrends(symbols); if (active) setTrends(values); } catch { /* Quotes remain available without trend history. */ }
    };
    void read(getMarketOverview, setMarket).then(readTrends);
    // Independent of the snapshot: the snapshot can be missing while index closes are stored.
    void read(() => getIndexHistory(INDEX_SYMBOL), setHistory);
    const refresh = async () => {
      if (document.hidden || refreshing) return;
      refreshing = true;
      const results = await Promise.allSettled([getMarketOverview(), getMarketFreshness(), getIndexHistory(INDEX_SYMBOL), getEventFeed()]);
      if (active) {
        if (results[0].status === "fulfilled") { setMarket({ status: "ready", data: results[0].value }); void readTrends(results[0].value); }
        if (results[1].status === "fulfilled") setFreshness({ status: "ready", data: results[1].value });
        if (results[2].status === "fulfilled") setHistory({ status: "ready", data: results[2].value });
        if (results[3].status === "fulfilled") setEvents({ status: "ready", data: results[3].value.events });
        if (results.some(result => result.status === "rejected")) {
          setFreshness(current => ({ ...current, error: "Automatic refresh failed; the last loaded session remains displayed." }));
        }
      }
      refreshing = false;
    };
    const visible = () => { if (!document.hidden) void refresh(); };
    const timer = setInterval(() => void refresh(), 3_600_000);
    document.addEventListener("visibilitychange", visible);
    return () => { active = false; clearInterval(timer); document.removeEventListener("visibilitychange", visible); };
  }, [revision]);

  return { trends, market, freshness, companies, events, history, reload: () => setRevision(value => value + 1) };
}
