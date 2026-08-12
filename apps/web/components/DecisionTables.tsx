import { Icon } from "@/components/Icon";
import { ComparisonMetric } from "@/lib/api";
import { classifyChange, formatMetric } from "@/lib/analytics";

const title=(input:string)=>input.toLowerCase()
  .replaceAll("_"," ")
  .replace(/^max\b/,"maximum")
  .replace(/^min\b/,"minimum")
  .replace(/\b\w/g,letter=>letter.toUpperCase());
const value=(input:unknown)=>typeof input==="number"?input.toFixed(4):input==null?"—":String(input);

type ComplianceProps={status?:"PASS"|"BREACH"|"NOT_EVALUATED";checks?:Array<Record<string,unknown>>;violations:Array<Record<string,unknown>>;not_evaluated?:Array<Record<string,unknown>>};
export function ComplianceTable({status,checks,violations,not_evaluated}:ComplianceProps){
  const allChecks=checks??[],unavailable=not_evaluated??[],resolved=status??(violations.length?"BREACH":"NOT_EVALUATED");
  if(resolved==="PASS")return <div className="empty-state !min-h-24"><Icon name="check"/><strong>Within evaluated mandate</strong><span>All required, evaluable checks passed ({allChecks.length} checks).</span></div>;
  return <div className="grid gap-3">{resolved==="NOT_EVALUATED"?<div className="notice notice-warn"><Icon name="warning"/><strong>Not fully evaluated</strong></div>:null}{violations.length?<section><h3 className="mb-2 text-xs font-bold">Hard breaches</h3><div className="table-wrap"><table className="data-table"><thead><tr><th>Constraint</th><th>Subject</th><th>Observed</th><th>Required</th><th>Status</th></tr></thead><tbody>{violations.map((row,index)=><tr key={`${String(row.code)}-${index}`}><td className="font-semibold">{title(String(row.code??"mandate constraint"))}</td><td>{String(row.symbol??row.sector??"Portfolio")}</td><td className="data-font">{value(row.actual)}</td><td className="data-font">{value(row.limit)}</td><td className="negative">BREACH</td></tr>)}</tbody></table></div></section>:null}{unavailable.length?<section><h3 className="mb-2 text-xs font-bold">Unavailable checks</h3><div className="divider-list">{unavailable.map((row,index)=><div className="p-3 text-xs" key={`${String(row.code)}-${index}`}><strong>{String(row.label??title(String(row.code??"check")))}</strong><p className="mt-1 text-muted">{String(row.message??"Required input is unavailable.")}</p></div>)}</div></section>:null}</div>;
}

export function ComparisonTable({metrics}:{metrics:ComparisonMetric[]}){
  return <div className="table-wrap"><table className="data-table proposal-comparison-table"><thead><tr><th>Measure</th><th>Current</th><th>Proposed</th><th>Change</th><th>Interpretation</th></tr></thead><tbody>{metrics.map(metric=>{const delta=metric.delta??null;const classification=metric.classification??classifyChange(delta,metric.preferred_direction);const tone=classification==="IMPROVED"?"positive":classification==="WORSENED"?"negative":"";return <tr key={metric.key}><td><strong>{metric.label}</strong>{metric.availability_note?<p className="text-[10px] text-muted">{metric.availability_note}</p>:null}</td><td className="data-font">{formatMetric(metric.current,metric.unit)}</td><td className="data-font">{formatMetric(metric.proposed,metric.unit)}</td><td className={`data-font ${tone}`}>{formatMetric(delta,metric.unit)}</td><td>{title(classification)}</td></tr>})}</tbody></table></div>;
}

export function Diagnostic({title,text}:{title:string;text:string}){return <div className="notice notice-warn"><Icon name="warning"/><span><strong>{title}</strong> {text}</span></div>}
