import { request } from "@/lib/api/client";

export type Exchange={code:string;name:string;timezone:string};
export type Company={id:string;symbol:string;name:string;sector:string;exchange:Exchange;official_website?:string|null;psx_url?:string|null;description?:string|null;is_active:boolean};
export type MarketPrice={symbol:string;trade_date:string;open:string;high:string;low:string;close:string;previous_close:string;change:string;change_percent:string;volume:number;value:string;market_cap?:string|null;source:string;source_url?:string|null;ingested_at:string};
export type MarketSnapshot={snapshot_date:string;index_name:string;index_value:string;index_change:string;index_change_percent:string;total_volume:number;total_value:string;source:string;ingested_at:string};
export type SectorDailyStats={sector:string;trade_date:string;total_volume:number;total_value:string;average_change_percent:string;advancers:number;decliners:number;unchanged:number;source:string};
export type CompanyDetail={company:Company;latest_price?:MarketPrice|null};
export type MarketOverview={snapshot?:MarketSnapshot|null;top_gainers:MarketPrice[];top_losers:MarketPrice[];top_volume:MarketPrice[];sectors:SectorDailyStats[]};
export type MarketFreshness={market_data_mode:string;refresh_seconds:number;last_successful_ingestion_at?:string|null;latest_trade_date?:string|null;latest_source?:string|null;latest_attempted_provider?:string|null;latest_used_provider?:string|null;is_stale:boolean;stale_warning?:string|null;backup_warning?:string|null;ingestion_age_seconds?:number|null;provider_mode_warning?:string|null;ingestion_staleness_warning?:string|null;fallback_provider_active:boolean;trade_date_status:"current"|"prior_session"|"stale"|"unknown";exchange_session_status:"open"|"closed"|"unknown";exchange_session_note?:string|null};
export type SourceHealth={source:string;status:"healthy"|"stale"|"partial"|"failed"|"never_run";last_attempt?:string|null;last_success?:string|null;latest_data_at?:string|null;attempted:number;accepted:number;updated:number;rejected:number;error?:string|null;freshness_sla_minutes?:number|null};
export type DataHealth={sources:SourceHealth[]};
export type CoverageCategory={available:boolean;count:number;latest_date?:string|null;reason?:string|null};
export type CompanyCompleteness={symbol:string;price:CoverageCategory&{observations:number};fundamentals:CoverageCategory&{fact_count:number;latest_period?:string|null};reports:CoverageCategory;announcements:CoverageCategory;news:CoverageCategory};

export const getMarketOverview=()=>request<MarketOverview>("/market/overview");
export const getMarketFreshness=()=>request<MarketFreshness>("/market/freshness");
export const getDataHealth=()=>request<DataHealth>("/ingestion/health");
export const getCompanyCompleteness=(symbol:string)=>request<CompanyCompleteness>(`/ingestion/companies/${encodeURIComponent(symbol)}/completeness`);
export function getCompanies(query?:string,options?:{signal?:AbortSignal}){const params=new URLSearchParams({limit:"1000"});if(query)params.set("q",query);return request<Company[]>(`/market/companies?${params.toString()}`,options?.signal?{signal:options.signal}:{})}
export const getCompanyDetail=(symbol:string)=>request<CompanyDetail>(`/market/company/${encodeURIComponent(symbol)}`);
export const getCompanyHistory=(symbol:string,limit=2000)=>request<MarketPrice[]>(`/market/company/${encodeURIComponent(symbol)}/history?limit=${encodeURIComponent(String(limit))}`);
