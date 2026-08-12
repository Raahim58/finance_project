export const WEIGHT_TOLERANCE = 1e-6;
export const CHANGE_TOLERANCE = 1e-8;

export type MetricUnit = "decimal"|"percentage_point"|"ratio"|"PKR"|"days"|"count";

export function formatMetric(value:number|null|undefined,unit:MetricUnit,digits=2){
  if(value==null||Number.isNaN(value))return "—";
  if(unit==="decimal")return `${(value*100).toFixed(digits)}%`;
  if(unit==="percentage_point")return `${value>0?"+":""}${value.toFixed(digits)} pp`;
  if(unit==="PKR")return `PKR ${new Intl.NumberFormat("en-PK",{maximumFractionDigits:digits}).format(value)}`;
  if(unit==="days")return `${value.toFixed(0)} days`;
  if(unit==="count")return value.toFixed(0);
  return value.toFixed(digits);
}

export function classifyChange(delta:number|null|undefined,direction:"higher"|"lower"|"neutral"){
  if(delta==null)return "NOT_EVALUATED" as const;
  if(direction==="neutral")return "REFERENCE" as const;
  if(Math.abs(delta)<=CHANGE_TOLERANCE)return "UNCHANGED" as const;
  return (direction==="higher"?delta>0:delta<0)?"IMPROVED" as const:"WORSENED" as const;
}

export function weightSummary(weights:Record<string,number>){
  const submittedSum=Object.values(weights).reduce((sum,value)=>sum+value,0);
  return {submittedSum,residual:1-submittedSum,valid:Object.values(weights).every(value=>value>=0)&&Math.abs(1-submittedSum)<=WEIGHT_TOLERANCE};
}

export function normalizeWeights(weights:Record<string,number>){
  const total=Object.values(weights).reduce((sum,value)=>sum+value,0);
  return total>0?Object.fromEntries(Object.entries(weights).map(([symbol,value])=>[symbol,value/total])):weights;
}
