export const human=(value:string)=>value.replaceAll("_"," ");
export const display=(value:unknown)=>value==null||value===""?"—":typeof value==="object"?JSON.stringify(value):String(value);
export const money=(value:unknown,currency="PKR")=>value==null||value===""||!Number.isFinite(Number(value))?"—":`${currency} ${new Intl.NumberFormat("en-PK",{maximumFractionDigits:2}).format(Number(value))}`;
export const date=(value?:string|null)=>{if(!value)return "—";const parsed=new Date(value.length===10?`${value}T00:00:00+05:00`:value);return Number.isNaN(parsed.valueOf())?"—":parsed.toLocaleDateString("en-GB",{day:"2-digit",month:"short",year:"numeric",timeZone:"Asia/Karachi"})};
