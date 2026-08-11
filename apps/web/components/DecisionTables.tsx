import { Icon } from "@/components/Icon";
import { ComparisonMetric } from "@/lib/api";

const title=(input:string)=>input
  .replaceAll("_"," ")
  .replace(/^max\b/,"maximum")
  .replace(/^min\b/,"minimum")
  .replace(/\b\w/g,letter=>letter.toUpperCase());
const value=(input:unknown)=>typeof input==="number"?input.toFixed(4):input==null?"—":String(input);

export function ComplianceTable({violations,empty="No hard mandate breaches were returned."}:{violations:Array<Record<string,unknown>>;empty?:string}){
  if(!violations.length)return <div className="empty-state !min-h-24"><Icon name="check"/><strong>Within implemented mandate checks</strong><span>{empty}</span></div>;
  return <div className="table-wrap"><table className="data-table"><thead><tr><th>Constraint</th><th>Subject</th><th>Observed</th><th>Required</th><th>Breach</th></tr></thead><tbody>{violations.map((row,index)=><tr key={`${String(row.code)}-${index}`}><td className="font-semibold">{title(String(row.code??"mandate constraint"))}</td><td>{String(row.symbol??row.sector??"Portfolio")}</td><td className="data-font">{value(row.actual)}</td><td className="data-font">{value(row.limit)}</td><td className="data-font negative">{value(row.breach)}</td></tr>)}</tbody></table></div>;
}

export function ComparisonTable({metrics}:{metrics:ComparisonMetric[]}){
  return <div className="table-wrap"><table className="data-table"><thead><tr><th>Measure</th><th>Current</th><th>Proposed</th><th>Change</th><th>Interpretation</th></tr></thead><tbody>{metrics.map(metric=>{const percent=metric.unit==="decimal";const format=(input?:number|null)=>input==null?"—":percent?`${(input*100).toFixed(2)}%`:input.toFixed(3);const delta=metric.delta??null;const improved=delta!=null&&metric.preferred_direction!=="neutral"&&(metric.preferred_direction==="higher"?delta>0:delta<0);return <tr key={metric.key}><td><strong>{metric.label}</strong>{metric.availability_note?<p className="text-[10px] text-muted">{metric.availability_note}</p>:null}</td><td className="data-font">{format(metric.current)}</td><td className="data-font">{format(metric.proposed)}</td><td className={`data-font ${delta==null?"":improved?"positive":"negative"}`}>{format(delta)}</td><td>{metric.preferred_direction==="neutral"?"Reference":delta==null?"Unavailable":improved?"Improved":"Worsened"}</td></tr>})}</tbody></table></div>;
}

export function Diagnostic({title,text}:{title:string;text:string}){return <div className="notice notice-warn"><Icon name="warning"/><span><strong>{title}</strong> {text}</span></div>}
