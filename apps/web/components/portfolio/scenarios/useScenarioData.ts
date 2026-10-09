"use client";

import { useCallback, useEffect, useState } from "react";
import { getMacroRegime, getScenarioRuns, getScenarioTemplates, type MacroRegime, type ScenarioResult, type ScenarioTemplate } from "@/lib/api";
import { getCompanies } from "@/lib/api/market";
import { getScenarioRunExtras, type ScenarioRunExtras } from "@/lib/api/portfolio-scenarios";

type Part<T> = { value: T; error: string | null };
const message = (error: unknown) => error instanceof Error ? error.message : "Request failed";

// Catalog, regime, per-run extras and company websites load independently so one failure never hides the rest.
export function useScenarioData(portfolioId: string, initialRuns: ScenarioResult[]) {
  const [templates, setTemplates] = useState<Part<ScenarioTemplate[]>>({ value: [], error: null });
  const [regime, setRegime] = useState<Part<MacroRegime | null>>({ value: null, error: null });
  const [extras, setExtras] = useState<Part<ScenarioRunExtras | null>>({ value: null, error: null });
  const [websites, setWebsites] = useState<Record<string, string | null>>({});
  const [runs, setRuns] = useState<ScenarioResult[]>(initialRuns);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => { if (initialRuns.length) setRuns(initialRuns); }, [initialRuns]);
  useEffect(() => {
    let live = true;
    setLoaded(false);
    void Promise.allSettled([getScenarioTemplates(), getMacroRegime(portfolioId), getScenarioRunExtras(portfolioId), getCompanies(), getScenarioRuns(portfolioId)]).then(([t, r, e, c, h]) => {
      if (!live) return;
      setTemplates(t.status === "fulfilled" ? { value: t.value, error: null } : { value: [], error: message(t.reason) });
      setRegime(r.status === "fulfilled" ? { value: r.value, error: null } : { value: null, error: message(r.reason) });
      setExtras(e.status === "fulfilled" ? { value: e.value, error: null } : { value: null, error: message(e.reason) });
      if (c.status === "fulfilled") setWebsites(Object.fromEntries(c.value.map(company => [company.symbol, company.official_website ?? null])));
      if (h.status === "fulfilled") setRuns(h.value);
      setLoaded(true);
    });
    return () => { live = false; };
  }, [portfolioId]);

  const refresh = useCallback(async () => {
    const [r, e] = await Promise.allSettled([getScenarioRuns(portfolioId), getScenarioRunExtras(portfolioId)]);
    if (r.status === "fulfilled") setRuns(r.value);
    if (e.status === "fulfilled") setExtras({ value: e.value, error: null });
    else setExtras(previous => ({ value: previous.value, error: message(e.reason) }));
  }, [portfolioId]);

  return { templates, regime, extras, websites, runs, loaded, refresh };
}
