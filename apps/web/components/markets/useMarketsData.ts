"use client";

import { useEffect, useState } from "react";
import { getCompanies, getIndexHistory, getMarketFreshness, getMarketOverview, type Company, type IndexClose, type MarketFreshness, type MarketOverview } from "@/lib/api";
import { getEventFeed, type ResearchEventView } from "@/lib/api/research";
import type { Resource } from "@/components/overview/useOverviewData";

const loading = <T,>(): Resource<T> => ({ status: "loading", data: null });

// The index tracked by the snapshot, e.g. "KSE-100" -> history key "KSE-100" (server normalises).
export function useMarketsData() {
  const [revision, setRevision] = useState(0);
  const [market, setMarket] = useState<Resource<MarketOverview>>(loading);
  const [freshness, setFreshness] = useState<Resource<MarketFreshness>>(loading);
  const [companies, setCompanies] = useState<Resource<Company[]>>(loading);
  const [events, setEvents] = useState<Resource<ResearchEventView[]>>(loading);
  const [history, setHistory] = useState<Resource<IndexClose[]>>(loading);

  useEffect(() => {
    let active = true;
    const read = async <T,>(fetcher: () => Promise<T>, setter: (value: Resource<T>) => void) => {
      setter(loading<T>());
      try { const data = await fetcher(); if (active) setter({ status: "ready", data }); return data; }
      catch (error) { if (active) setter({ status: "error", data: null, error: error instanceof Error ? error.message : "Request failed" }); return null; }
    };
    void read(() => getCompanies(), setCompanies);
    void read(getMarketFreshness, setFreshness);
    void read(async () => (await getEventFeed()).events, setEvents);
    void read(getMarketOverview, setMarket).then(overview => {
      const name = overview?.snapshot?.index_name;
      if (!active) return;
      if (name) void read(() => getIndexHistory(name), setHistory);
      else setHistory({ status: "ready", data: [] });
    });
    return () => { active = false; };
  }, [revision]);

  return { market, freshness, companies, events, history, reload: () => setRevision(value => value + 1) };
}
