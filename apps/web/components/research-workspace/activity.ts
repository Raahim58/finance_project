import type {AuditEvent,Transaction} from "@/lib/api";
export type ActivityRow={id:string;date:string;kind:string;title:string;portfolioId:string|null;transaction?:Transaction;audit?:AuditEvent};
export function activityRows(transactions:Transaction[],events:AuditEvent[]):ActivityRow[]{return [...transactions.map(transaction=>({id:`transaction:${transaction.id}`,date:transaction.transaction_date,kind:"transaction",title:`${transaction.transaction_type.replaceAll("_"," ")} ${transaction.symbol}`,portfolioId:transaction.portfolio_id,transaction})),...events.map(audit=>({id:`audit:${audit.id}`,date:audit.created_at,kind:audit.entity_type,title:audit.event_type.replaceAll("_"," "),portfolioId:audit.portfolio_id??null,audit}))].sort((a,b)=>b.date.localeCompare(a.date)||a.id.localeCompare(b.id))}
export function activityWithin(date:string,days:string,now=Date.now()){if(!days)return true;const parsed=new Date(date.length===10?`${date}T00:00:00+05:00`:date).valueOf();return Number.isFinite(parsed)&&parsed>=now-Number(days)*86400000}

const cap=(value:string)=>{const text=value.replaceAll("_"," ").trim();return text?text[0].toUpperCase()+text.slice(1):text};
const pkr=(value:number)=>`${value<0?"−":""}PKR ${new Intl.NumberFormat("en-PK",{maximumFractionDigits:0}).format(Math.abs(value))}`;
export const activityLabel=(row:ActivityRow)=>row.transaction?cap(row.transaction.transaction_type):cap(row.kind);
export function activityHeadline(row:ActivityRow){
 if(row.transaction)return `${cap(row.transaction.transaction_type)} · ${row.transaction.symbol}`;
 const state=(row.audit?.new_state??{}) as Record<string,unknown>;
 return typeof state.name==="string"&&state.name?state.name:cap(row.title);
}
export function activityDetail(row:ActivityRow):string{
 const transaction=row.transaction;
 if(transaction){const quantity=Number(transaction.quantity),price=Number(transaction.price);const parts:string[]=[];if(Number.isFinite(quantity)&&transaction.quantity)parts.push(`${new Intl.NumberFormat("en-PK",{maximumFractionDigits:2}).format(quantity)} shares`);if(Number.isFinite(price)&&transaction.price)parts.push(`at PKR ${new Intl.NumberFormat("en-PK",{maximumFractionDigits:2}).format(price)}`);return parts.join(" ")||cap(transaction.notes??"")}
 const audit=row.audit;if(!audit)return "";
 const before=(audit.previous_state??{}) as Record<string,unknown>,after=(audit.new_state??{}) as Record<string,unknown>;
 if(typeof after.status==="string"&&typeof before.status==="string")return `Status changed from ${before.status} to ${after.status}`;
 if(typeof after.pnl==="number")return `Estimated P&L ${pkr(after.pnl)}${typeof after.compliance_status==="string"?` · Mandate ${cap(after.compliance_status).toLowerCase()}`:""}`;
 if(typeof after.objective==="string")return `${cap(after.objective)}${typeof after.status==="string"?` · ${cap(after.status).toLowerCase()}`:""}`;
 return audit.note??"";
}
export function activityAmount(row:ActivityRow):number|null{
 const transaction=row.transaction;if(!transaction)return null;
 const amount=Number(transaction.amount);if(Number.isFinite(amount)&&amount!==0)return amount;
 const value=Number(transaction.quantity)*Number(transaction.price);return Number.isFinite(value)&&value!==0?value:null;
}
