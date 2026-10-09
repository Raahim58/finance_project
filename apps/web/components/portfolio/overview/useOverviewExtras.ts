"use client";

import { useEffect, useState } from "react";
import { getAlerts, getCompanies, getCompanyHistory, getIndexHistory, getTransactions, type IndexClose, type Transaction } from "@/lib/api";
import { getPortfolioEventIntelligence, type PortfolioEventIntelligence } from "@/lib/api/research";
import { closesOf, type Closes } from "@/lib/portfolio-overview";

export type Resource<T> = { value: T; failed: boolean };
export type OverviewAlert = Record<string, unknown>;

// Supplementary reads for the Overview tab. Each slice fails independently so one outage never hides the rest.
export function useOverviewExtras(portfolioId: string, symbols: string[]) {
  const [transactions, setTransactions] = useState<Resource<Transaction[] | null>>({ value: null, failed: false });
  const [alerts, setAlerts] = useState<Resource<OverviewAlert[] | null>>({ value: null, failed: false });
  const [events, setEvents] = useState<Resource<PortfolioEventIntelligence | null>>({ value: null, failed: false });
  const [index, setIndex] = useState<Resource<IndexClose[] | null>>({ value: null, failed: false });
  const [history, setHistory] = useState<Record<string, Closes | undefined>>({});
  const [websites, setWebsites] = useState<Record<string, string | null | undefined>>({});
  const key = symbols.join("|");

  useEffect(() => {
    let active = true;
    const load = <T,>(read: () => Promise<T>, set: (resource: Resource<T | null>) => void) => {
      set({ value: null, failed: false });
      read().then(value => { if (active) set({ value, failed: false }); }).catch(() => { if (active) set({ value: null, failed: true }); });
    };
    load(() => getTransactions(portfolioId), setTransactions);
    load(() => getAlerts(portfolioId), setAlerts);
    load(() => getPortfolioEventIntelligence(portfolioId, 3), setEvents);
    load(() => getIndexHistory("KSE-100"), setIndex);
    return () => { active = false; };
  }, [portfolioId]);

  useEffect(() => {
    let active = true;
    setHistory({});
    symbols.forEach(symbol => getCompanyHistory(symbol, 400).then(rows => { if (active) setHistory(current => ({ ...current, [symbol]: closesOf(rows) })); }).catch(() => { if (active) setHistory(current => ({ ...current, [symbol]: [] })); }));
    getCompanies().then(rows => { if (active) setWebsites(Object.fromEntries(rows.map(company => [company.symbol, company.official_website]))); }).catch(() => undefined);
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { transactions, alerts, events, index, history, websites };
}
