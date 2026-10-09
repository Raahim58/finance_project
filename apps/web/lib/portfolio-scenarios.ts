import type { HistoricalReplay, ScenarioResult, ScenarioTemplate } from "@/lib/api";
import type { ScenarioRunExtra } from "@/lib/api/portfolio-scenarios";
import { numeric } from "@/lib/overview";

export type HoldingImpact = { symbol: string; name: string | null; sector: string | null; weight: number | null; priceImpact: number | null; pnl: number | null; contribution: number | null; unmapped: boolean };
export type SectorImpact = { sector: string; weight: number | null; impact: number | null; pnl: number; contribution: number | null };

// Weights and contributions are fractions of total portfolio value at run time (cash included).
function ratio(part: number | null, whole: number | null): number | null {
  return part == null || whole == null || whole <= 0 ? null : part / whole;
}

export function holdingImpacts(result: ScenarioResult, names: Record<string, string> = {}): HoldingImpact[] {
  const total = numeric(result.portfolio_value);
  return result.positions.map(row => {
    const symbol = String(row.symbol ?? "");
    const value = numeric(row.value), pnl = numeric(row.pnl);
    const mapping = row.mapping_sources;
    return {
      symbol, name: names[symbol] ?? null, sector: typeof row.sector === "string" ? row.sector : null,
      weight: ratio(value, total), priceImpact: numeric(row.shock), pnl, contribution: ratio(pnl, total),
      unmapped: Array.isArray(mapping) && mapping.length === 0 && numeric(row.shock) === 0,
    };
  }).sort((a, b) => Math.abs(b.contribution ?? 0) - Math.abs(a.contribution ?? 0));
}

export function sectorImpacts(result: ScenarioResult): SectorImpact[] {
  const total = numeric(result.portfolio_value);
  const values: Record<string, number> = {};
  for (const row of result.positions) {
    const sector = typeof row.sector === "string" && row.sector ? row.sector : "Unknown";
    values[sector] = (values[sector] ?? 0) + (numeric(row.value) ?? 0);
  }
  return Object.entries(result.sector_contributions).map(([sector, pnl]) => ({
    sector, pnl, weight: ratio(values[sector] ?? null, total), impact: ratio(pnl, values[sector] ?? null), contribution: ratio(pnl, total),
  })).sort((a, b) => Math.abs(b.contribution ?? 0) - Math.abs(a.contribution ?? 0));
}

// Bar length relative to the largest magnitude in the table.
export function barWidth(value: number | null, rows: Array<number | null>): number {
  const peak = Math.max(0, ...rows.map(row => Math.abs(row ?? 0)));
  return value == null || peak === 0 ? 0 : Math.min(100, Math.abs(value) / peak * 100);
}

export function formatSigned(value: number | null | undefined, digits = 1, suffix = "%", scale = 100) {
  const result = numeric(value);
  if (result == null) return "—";
  const scaled = result * scale;
  const text = Math.abs(scaled).toFixed(digits);
  return `${Number(text) === 0 ? "" : scaled > 0 ? "+" : "-"}${text}${suffix}`;
}
export const formatPp = (value: number | null | undefined) => formatSigned(value, 1, " pp");
export function formatPkr(value: number | null | undefined, signed = true) {
  const result = numeric(value);
  if (result == null) return "—";
  const text = new Intl.NumberFormat("en-PK", { maximumFractionDigits: 0 }).format(Math.abs(result));
  return `PKR ${signed && result !== 0 ? (result > 0 ? "+" : "-") : result < 0 ? "-" : ""}${text}`;
}
export function formatRunTime(value?: string | null) {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Karachi" }).format(date).replace(",", "");
}

export const tone = (value: number | null | undefined) => (numeric(value) ?? 0) < 0 ? "negative" : (numeric(value) ?? 0) > 0 ? "positive" : "";

export function shockChips(shocks: ScenarioRunExtra["shocks"] | undefined): string[] {
  if (!shocks) return [];
  const fmt = (value: number) => formatSigned(value, 1);
  return [
    ...Object.entries(shocks.instruments).map(([key, value]) => `${key} ${fmt(value)}`),
    ...Object.entries(shocks.sectors).map(([key, value]) => `${key} ${fmt(value)}`),
    ...Object.entries(shocks.factors).map(([key, value]) => `${key} factor ${fmt(value)}`),
  ];
}
export function templateChips(template: Pick<ScenarioTemplate, "sector_shocks" | "factor_shocks" | "fallback_security_shock">): string[] {
  return shockChips({ instruments: {}, sectors: template.sector_shocks, factors: template.factor_shocks });
}

// Run names for templates are `${name} · ${version}`; this recovers the catalog entry for that run.
export function templateForRun(name: string, templates: ScenarioTemplate[]) {
  return templates.find(template => name === `${template.name} · ${template.version}`) ?? null;
}

export function templatePayload(template: ScenarioTemplate, symbols: string[]) {
  const direct = template.fallback_security_shock == null ? {} : Object.fromEntries(symbols.map(symbol => [symbol, template.fallback_security_shock as number]));
  return { name: `${template.name} · ${template.version}`, scenario_type: "hypothetical", shocks: direct, sector_shocks: template.sector_shocks, factor_shocks: template.factor_shocks };
}

export type CustomInput = { symbol: string; securityShock: string; sector: string; sectorShock: string; factor: string; factorShock: string };
const percentToDecimal = (text: string) => { const parsed = numeric(text); return parsed == null ? null : parsed / 100; };

// Returns the request body, or an error string when no complete shock was entered.
export function customPayload(input: CustomInput): { payload: Record<string, unknown> } | { error: string } {
  const security = input.symbol ? percentToDecimal(input.securityShock) : null;
  const sector = input.sector ? percentToDecimal(input.sectorShock) : null;
  const factor = input.factor.trim() ? percentToDecimal(input.factorShock) : null;
  if (security == null && sector == null && factor == null) return { error: "Enter at least one complete shock (target and percentage)." };
  const parts = [security != null ? `${input.symbol} ${formatSigned(security)}` : "", sector != null ? `${input.sector} ${formatSigned(sector)}` : "", factor != null ? `${input.factor.trim()} ${formatSigned(factor)}` : ""].filter(Boolean);
  return { payload: {
    name: `Custom: ${parts.join(", ")}`,
    scenario_type: security != null && sector == null && factor == null ? "sensitivity" : "hypothetical",
    shocks: security != null ? { [input.symbol]: security } : {},
    sector_shocks: sector != null ? { [input.sector]: sector } : {},
    factor_shocks: factor != null ? { [input.factor.trim()]: factor } : {},
  } };
}

export function replayContributions(replay: HistoricalReplay) {
  return Object.entries(replay.sector_pnl_contribution).map(([sector, pnl]) => ({ sector, pnl, contribution: ratio(pnl, numeric(replay.start_value)) }))
    .sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
}

export function typeLabel(type?: string | null) {
  if (!type) return null;
  return type === "hypothetical" ? "Multi-factor" : type.replace(/^\w/, letter => letter.toUpperCase());
}
