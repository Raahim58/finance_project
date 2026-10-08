import type { IpsVersion } from "@/lib/api";
export type IpsForm = Record<"goal"|"capital"|"target"|"years"|"contribution"|"capacity"|"willingness"|"overall"|"liquidity"|"minCash"|"maxWeight"|"maxSector"|"volatility"|"beta"|"longOnly"|"shariah"|"benchmark"|"proxy"|"riskFree", string>;
export const blankIps: IpsForm = {goal:"",capital:"",target:"",years:"",contribution:"",capacity:"",willingness:"",overall:"",liquidity:"",minCash:"",maxWeight:"",maxSector:"",volatility:"",beta:"",longOnly:"",shariah:"",benchmark:"",proxy:"",riskFree:""};
const text = (value: unknown) => value == null ? "" : String(value);
const percent = (value: unknown) => value == null ? "" : String(Number(value)*100);
export function fromIps(version?: IpsVersion): IpsForm {
  if (!version) return {...blankIps};
  const c = version.constraints as Record<string, unknown>, o = (c.objective_inputs ?? {}) as Record<string, unknown>;
  return {goal:text(c.goal),capital:text(o.starting_capital),target:text(o.target_value),years:text(o.horizon_years),contribution:text(o.annual_contribution),capacity:text(c.risk_capacity),willingness:text(c.risk_willingness),overall:text(c.overall_risk_tolerance),liquidity:text(c.liquidity_requirement),minCash:percent(c.min_cash_weight),maxWeight:percent(c.max_instrument_weight),maxSector:percent(c.max_sector_weight),volatility:percent(c.target_volatility),beta:text(c.target_beta),longOnly:text(c.long_only),shariah:text(c.shariah_only),benchmark:text(c.performance_benchmark_symbol ?? c.benchmark_symbol),proxy:text(c.capm_market_proxy_symbol),riskFree:text(c.risk_free_series_key)};
}
// Preserve unedited constraints and the dated/real-goal basis when creating a new version.
export function ipsPayload(form: IpsForm, version?: IpsVersion): Record<string, unknown> {
  const constraints: Record<string, unknown> = {...version?.constraints};
  const fields: Array<[keyof IpsForm, string, number]> = [["minCash","min_cash_weight",100],["maxWeight","max_instrument_weight",100],["maxSector","max_sector_weight",100],["volatility","target_volatility",100],["beta","target_beta",1]];
  for (const [field, key, scale] of fields) { if (form[field] !== "") constraints[key] = Number(form[field])/scale; else delete constraints[key]; }
  for (const [field,key] of [["longOnly","long_only"],["shariah","shariah_only"]] as const) { if (form[field] !== "") constraints[key] = form[field] === "true"; else delete constraints[key]; }
  if (form.riskFree) constraints.risk_free_series_key = form.riskFree; else delete constraints.risk_free_series_key;
  for (const key of ["benchmark_symbol","performance_benchmark_symbol","capm_market_proxy_symbol","goal","risk_capacity","risk_willingness","overall_risk_tolerance","liquidity_requirement"]) delete constraints[key];
  const method = version?.constraints.required_return_method as Record<string, unknown> | undefined;
  return {constraints,goal:form.goal || null,starting_capital:form.capital ? Number(form.capital) : null,target_value:form.target ? Number(form.target) : null,horizon_years:form.years ? Number(form.years) : null,annual_contribution:form.contribution ? Number(form.contribution) : 0,risk_capacity:form.capacity || null,risk_willingness:form.willingness || null,overall_risk_tolerance:form.overall || null,liquidity_requirement:form.liquidity ? Number(form.liquidity) : null,performance_benchmark_symbol:form.benchmark || null,capm_market_proxy_symbol:form.proxy || null,...(method ? {valuation_date:method.valuation_date,target_date:form.years === fromIps(version).years ? method.target_date : null,target_value_is_real:method.target_value_is_real,inflation_rate:method.inflation_rate,dated_contributions:Array.isArray(method.dated_contributions) ? method.dated_contributions.map(item => { const row=item as Record<string,unknown>; return {contribution_date:row.date,amount:row.amount}; }) : []} : {})};
}
