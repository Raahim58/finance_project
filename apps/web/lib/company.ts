import type { CompanyResearch } from "./api";
import { formatNumber, numeric } from "./overview";

export type CompanyFact=CompanyResearch["fundamentals"][number];
export function companyFacts(research:CompanyResearch|null):CompanyFact[] {
  const sections=research?.context.sections as Record<string,{data?:{fundamentals?:Array<Record<string,unknown>>}}>|undefined;
  const raw=sections?.company_facts?.data?.fundamentals;
  // Read the structured context, preserving statement dimensions on older adapters.
  if(raw?.length) return raw.map(row=>({id:row.id as string,taxonomy_key:String(row.metric),value:row.value as string,
    unit:String(row.unit??""),currency:row.currency as string|null,period_type:String(row.period_type??""),
    period_start:row.period_start as string|null,period_end:String(row.period_end??""),filing_date:row.filing_date as string|null,
    accounting_basis:row.accounting_basis as string|null,source_label:row.source as string|null,
    source_url:row.source_url as string|null,document_id:row.document_id as string|null,page_number:row.page_number as number|null,
    classification:String(row.classification??"filing_extracted"),provenance:{source_name:row.source as string|null,document_type:"structured_financials",is_synthetic:false,ingested_at:null}}));
  return research?.fundamentals??[];
}
export function factValue(value:unknown,unit:string,currency?:string|null){
  if(numeric(value)==null)return "—";
  if(unit==="percent"||unit==="%")return `${formatNumber(value)}%`;
  if(unit==="fraction")return `${formatNumber(Number(value)*100)}%`;
  if(unit==="ratio"||unit==="multiple")return `${formatNumber(value)}×`;
  return `${currency??(unit==="PKR"?"PKR":"")} ${formatNumber(value)}${!currency&&unit!=="PKR"&&unit?` ${unit}`:""}`.trim();
}
export const ratioDefinitions=[
  {key:"pe_ratio",label:"P/E ratio",group:"Valuation",unit:"multiple",formula:"Price ÷ trailing earnings per share",inputs:["price","earnings_per_share_ttm"]},
  {key:"pb_ratio",label:"P/B ratio",group:"Valuation",unit:"multiple",formula:"Price ÷ book value per share",inputs:["price","book_value_per_share"]},
  {key:"dividend_yield",label:"Dividend yield",group:"Valuation",unit:"fraction",formula:"Trailing cash dividends per share ÷ price",inputs:["dividend_per_share_ttm","price"]},
  {key:"operating_margin",label:"Operating margin",group:"Profitability",unit:"fraction",formula:"Operating profit ÷ revenue",inputs:["ebit","revenue"]},
  {key:"net_margin",label:"Net margin",group:"Profitability",unit:"fraction",formula:"Net income ÷ revenue",inputs:["net_income","revenue"]},
  {key:"return_on_equity",label:"ROE",group:"Profitability",unit:"fraction",formula:"Net income ÷ average equity",inputs:["net_income","average_equity"]},
  {key:"current_ratio",label:"Current ratio",group:"Liquidity",unit:"multiple",formula:"Current assets ÷ current liabilities",inputs:["current_assets","current_liabilities"]},
  {key:"quick_ratio",label:"Quick ratio",group:"Liquidity",unit:"multiple",formula:"(Cash + short-term investments + receivables) ÷ current liabilities",inputs:["cash","short_term_investments","receivables","current_liabilities"]},
  {key:"cash_ratio",label:"Cash ratio",group:"Liquidity",unit:"multiple",formula:"Cash and cash equivalents ÷ current liabilities",inputs:["cash","current_liabilities"]},
  {key:"operating_cash_flow",label:"Operating cash flow",group:"Cash flow",unit:"PKR",formula:"Reported net cash from operating activities",inputs:["operating_cash_flow"]},
  {key:"free_cash_flow",label:"Free cash flow",group:"Cash flow",unit:"PKR",formula:"Operating cash flow − capital expenditure",inputs:["operating_cash_flow","capital_expenditure"]},
] as const;
export type RatioDefinition=typeof ratioDefinitions[number];
export function ratioValue(research:CompanyResearch|null,key:string){
  // Never derive ratios or substitute screening estimates on the client.
  return research?.derived_fundamentals.ratios?.[key];
}
export function factGroup(key:string){
  if(["assets","current_assets","liabilities","current_liabilities","equity","debt","cash","inventory","receivables","short_term_investments"].includes(key))return "balance";
  if(key.includes("cash_flow")||key.includes("capex")||key==="capital_expenditure")return "cash";
  return "income";
}
