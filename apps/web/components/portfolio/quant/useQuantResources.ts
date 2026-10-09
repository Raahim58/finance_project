"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CapitalMarketAssumptions, CapmSml, EfficientFrontier, PortfolioQuant, ReturnDistribution, RollingRisk,
  getCapitalMarketAssumptions, getCapmSml, getEfficientFrontier, getPortfolioQuant, getReturnDistribution, getRollingRisk,
} from "@/lib/api";
import type { QuantTabId } from "@/lib/portfolio-quant";

const REQUEST_TIMEOUT_MS = 20000;

export type Resource<T> = { status: "idle" | "loading" | "success" | "error"; value: T | null; error?: string; retry: () => void };

// Loads one analytics payload once per portfolio (and per retry), with a hard timeout so a stalled
// request surfaces as a retryable error instead of an endless skeleton.
function useResource<T>(portfolioId: string, enabled: boolean, load: (portfolioId: string) => Promise<T>): Resource<T> {
  const [state, setState] = useState<{ owner: string; status: Resource<T>["status"]; value: T | null; error?: string }>({ owner: portfolioId, status: "idle", value: null });
  const [tick, setTick] = useState(0);
  const startedRef = useRef("");
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    if (!enabled) return;
    const token = `${portfolioId}:${tick}`;
    if (startedRef.current === token) return;
    startedRef.current = token;
    setState({ owner: portfolioId, status: "loading", value: null });
    const timer = setTimeout(() => {
      setState(current => startedRef.current === token && current.status === "loading" ? { owner: portfolioId, status: "error", value: null, error: "Request timed out." } : current);
    }, REQUEST_TIMEOUT_MS);
    loadRef.current(portfolioId).then(value => {
      clearTimeout(timer);
      if (startedRef.current === token) setState({ owner: portfolioId, status: "success", value });
    }).catch((reason: unknown) => {
      clearTimeout(timer);
      if (startedRef.current === token) setState({ owner: portfolioId, status: "error", value: null, error: reason instanceof Error ? reason.message : "Request failed" });
    });
  }, [portfolioId, enabled, tick]);
  useEffect(() => () => { startedRef.current = ""; }, [portfolioId]);
  const retry = useCallback(() => setTick(current => current + 1), []);
  const current = state.owner === portfolioId ? state : { status: "idle" as const, value: null, error: undefined };
  return { status: current.status, value: current.value, error: current.error, retry };
}

export function useQuantResources(portfolioId: string, tab: QuantTabId, hasQuant: boolean) {
  return {
    frontier: useResource<EfficientFrontier>(portfolioId, true, getEfficientFrontier),
    assumptions: useResource<CapitalMarketAssumptions>(portfolioId, true, getCapitalMarketAssumptions),
    quant: useResource<PortfolioQuant>(portfolioId, !hasQuant, getPortfolioQuant),
    capm: useResource<CapmSml>(portfolioId, tab === "capm", getCapmSml),
    rolling: useResource<RollingRisk>(portfolioId, tab === "rolling", id => getRollingRisk(id)),
    distribution: useResource<ReturnDistribution>(portfolioId, tab === "distribution", getReturnDistribution),
  };
}
