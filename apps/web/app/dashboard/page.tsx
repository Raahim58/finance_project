"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { BarChart, DonutChart, LineChart } from "@/components/WorkstationChart";
import { getAlerts,getMarketOverview,getPortfolioExposure,getPortfolioPerformance,getPortfolioQuant,getPortfolioRiskFlags,getPortfolioSummary,getPortfolios,MarketOverview,PortfolioExposure,PortfolioPerformancePoint,PortfolioQuant,PortfolioRiskFlags,PortfolioSummary } from "@/lib/api";

type Size="small"|"medium"|"wide"; type WidgetId="value"|"performance"|"allocation"|"risk"|"holdings"|"movers"|"alerts"|"macro"|"watchlist"|"events";
type WidgetConfig={id:WidgetId;size:Size};
const defaults:WidgetConfig[]=[{id:"value",size:"small"},{id:"performance",size:"wide"},{id:"alerts",size:"medium"},{id:"allocation",size:"medium"},{id:"risk",size:"medium"},{id:"movers",size:"medium"},{id:"holdings",size:"wide"}];
const catalog:WidgetConfig[]=defaults;
const names:Record<WidgetId,string>={value:"Portfolio value",performance:"Performance",allocation:"Allocation",risk:"Risk contribution",holdings:"Holdings",movers:"Market movers",alerts:"Exceptions",macro:"Macro context",watchlist:"Watchlist",events:"Events"};
const span:Record<Size,string>={small:"md:col-span-4",medium:"md:col-span-6",wide:"md:col-span-12"};
const sizes:Size[]=["small","medium","wide"];

type Data={summary:PortfolioSummary|null;performance:PortfolioPerformancePoint[];exposure:PortfolioExposure|null;quant:PortfolioQuant|null;risk:PortfolioRiskFlags|null;market:MarketOverview|null;alerts:Array<Record<string,unknown>>};
const blank:Data={summary:null,performance:[],exposure:null,quant:null,risk:null,market:null,alerts:[]};
const money=(v:unknown)=>`PKR ${new Intl.NumberFormat("en-PK",{notation:"compact",maximumFractionDigits:1}).format(Number(v||0))}`;
const pct=(v:unknown)=>v==null?"—":`${Number(v)>0?"+":""}${Number(v).toFixed(2)}%`;

export default function DashboardPage(){
  const [widgets,setWidgets]=useState<WidgetConfig[]>(defaults); const [editing,setEditing]=useState(false); const [data,setData]=useState<Data>(blank); const [loading,setLoading]=useState(true); const [error,setError]=useState("");
  useEffect(()=>{const saved=localStorage.getItem("psx-dashboard-layout"); if(saved) try{setWidgets(JSON.parse(saved))}catch{};
    void getPortfolios().then(async ps=>{const p=ps.find(x=>x.is_default)??ps[0]; const [market,alerts]=await Promise.all([getMarketOverview().catch(()=>null),getAlerts(p?.id).catch(()=>[])]); if(!p){setData(d=>({...d,market,alerts}));return;} const [summary,performance,exposure,quant,risk]=await Promise.all([getPortfolioSummary(p.id),getPortfolioPerformance(p.id).catch(()=>[]),getPortfolioExposure(p.id).catch(()=>null),getPortfolioQuant(p.id).catch(()=>null),getPortfolioRiskFlags(p.id).catch(()=>null)]); setData({summary,performance,exposure,quant,risk,market,alerts});}).catch((e:Error)=>setError(e.message)).finally(()=>setLoading(false));
  },[]);
  function save(next:WidgetConfig[]){setWidgets(next);localStorage.setItem("psx-dashboard-layout",JSON.stringify(next));}
  function move(i:number,d:number){const n=[...widgets],to=i+d;if(to<0||to>=n.length)return;[n[i],n[to]]=[n[to],n[i]];save(n)}
  function resize(i:number){save(widgets.map((w,j)=>j===i?{...w,size:sizes[(sizes.indexOf(w.size)+1)%sizes.length]}:w))}
  function remove(i:number){save(widgets.filter((_,j)=>j!==i))}
  const hidden=catalog.filter(d=>!widgets.some(w=>w.id===d.id));
  const exceptionCount=(data.risk?.flags.length??0)+data.alerts.length;
  return <div className="page-wrap">
    <header className="page-heading"><div><p className="eyebrow">Investment workspace</p><h1 className="page-title">Investment overview</h1><p className="page-subtitle">The portfolio first—followed by performance, exceptions, allocation and relevant market context.</p></div><div className="flex flex-wrap gap-2"><button className="btn btn-secondary" onClick={()=>setEditing(!editing)}><Icon name={editing?"check":"settings"}/>{editing?"Finish layout":"Customize"}</button><Link className="btn btn-primary" href="/portfolios">Review portfolios <Icon name="chevron"/></Link></div></header>
    {error?<div className="notice notice-error mb-4"><Icon name="warning"/><span><strong>Workspace data unavailable.</strong> {error}</span></div>:null}
    {!loading&&!error?<div className="source-rail mb-5 flex flex-wrap items-center justify-between gap-4 px-5 py-4"><div className="flex items-center gap-3"><span className={`grid h-8 w-8 place-items-center rounded-full ${exceptionCount?"bg-[#fbf2df] text-[#a86f18]":"bg-[#e8f3ee] text-accent"}`}><Icon name={exceptionCount?"warning":"check"} size={16}/></span><div><p className="text-[13px] font-semibold">{exceptionCount?`${exceptionCount} active exception${exceptionCount===1?"":"s"} ${exceptionCount===1?"requires":"require"} review`:"No active portfolio exceptions"}</p><p className="text-[11px] text-muted">{data.summary?.portfolio.name??"No portfolio selected"}</p></div></div><p className="text-[11px] text-muted">As of {data.summary?.data_freshness_date??"unavailable"} · {data.summary?.data_source??"source unavailable"}</p></div>:null}
    {editing?<div className="mb-5 flex flex-wrap items-center gap-2 rounded-xl border border-dashed border-line bg-white p-4"><span className="mr-2 text-xs font-semibold">Add view</span>{hidden.map(w=><button key={w.id} className="btn btn-secondary" onClick={()=>save([...widgets,w])}><Icon name="plus" size={14}/>{names[w.id]}</button>)}{!hidden.length?<span className="text-xs text-muted">All views are visible. Use arrows to reorder and expand to resize.</span>:null}</div>:null}
    <div className="grid grid-cols-1 gap-4 md:grid-cols-12">
      {widgets.map((w,i)=><section key={w.id} className={`panel min-h-[210px] ${w.id==="performance"?"min-h-[370px]":""} ${span[w.size]}`}><div className="panel-head"><h2 className="panel-title">{names[w.id]}</h2>{editing?<div className="flex"><button className="icon-btn" aria-label={`Move ${names[w.id]} earlier`} disabled={i===0} onClick={()=>move(i,-1)}><Icon name="arrowUp"/></button><button className="icon-btn" aria-label={`Move ${names[w.id]} later`} disabled={i===widgets.length-1} onClick={()=>move(i,1)}><Icon name="arrowDown"/></button><button className="icon-btn" aria-label={`Resize ${names[w.id]}`} onClick={()=>resize(i)} title={`Current size: ${w.size}`}><Icon name="expand"/></button><button className="icon-btn" aria-label={`Remove ${names[w.id]}`} onClick={()=>remove(i)}><Icon name="close"/></button></div>:<span className="text-[11px] text-muted">{data.summary?.data_freshness_date??"No date"}</span>}</div><div className="panel-body h-[calc(100%-54px)]"><Widget id={w.id} data={data} loading={loading}/></div></section>)}
    </div>
  </div>;
}

function Widget({id,data,loading}:{id:WidgetId;data:Data;loading:boolean}){
  if(loading)return <div className="grid h-full content-center gap-3"><div className="skeleton h-6 w-1/2"/><div className="skeleton h-20 w-full"/></div>;
  const s=data.summary;
  if(id==="value")return s?<div className="flex h-full flex-col justify-between"><div><p className="metric-label">Total market value</p><p className="data-font mt-2 text-[30px] font-semibold tracking-[-.045em]">{money(s.total_value)}</p><p className={`mt-3 text-sm font-semibold ${Number(s.day_change)>=0?"positive":"negative"}`}>{pct(s.day_change_percent)} today · {money(s.day_change)}</p></div><p className="text-[11px] text-muted">{s.portfolio.name} · {s.data_source??"source unavailable"}</p></div>:<Missing text="Select or create a portfolio to monitor value."/>;
  if(id==="performance")return <LineChart height={290} percent labels={data.performance.map(x=>x.value_date)} values={data.performance.map(x=>Number(x.cumulative_twr_percent??0))}/>;
  if(id==="allocation")return <DonutChart height={205} labels={data.exposure?.by_sector.map(x=>x.sector)??[]} values={data.exposure?.by_sector.map(x=>Number(x.weight_percent))??[]}/>;
  if(id==="risk")return <BarChart height={205} horizontal percent labels={Object.keys(data.quant?.risk_contributions??{})} values={Object.values(data.quant?.risk_contributions??{}).map(v=>v*100)} color="#536b70"/>;
  if(id==="holdings")return s?.holdings.length?<div className="table-wrap"><table className="data-table dashboard-holdings-table"><colgroup><col className="holdings-security"/><col className="holdings-sector"/><col className="holdings-value"/><col className="holdings-day"/><col className="holdings-pnl"/></colgroup><thead><tr><th scope="col">Security</th><th scope="col">Sector</th><th scope="col">Market value</th><th scope="col">Day</th><th scope="col">Unrealized P&amp;L</th></tr></thead><tbody>{s.holdings.slice(0,8).map(h=><tr key={h.holding_id}><td><Link className="font-bold text-accent" href={`/companies/${h.symbol}`}>{h.symbol}</Link></td><td>{h.sector}</td><td className="data-font">{money(h.market_value)}</td><td className={`data-font ${Number(h.day_change_percent)>=0?"positive":"negative"}`}>{pct(h.day_change_percent)}</td><td className={`data-font ${Number(h.unrealized_gain_loss)>=0?"positive":"negative"}`}>{money(h.unrealized_gain_loss)}</td></tr>)}</tbody></table></div>:<Missing text="Holdings will appear after positions are added."/>;
  if(id==="movers"){const rows=[...(data.market?.top_gainers.slice(0,3)??[]),...(data.market?.top_losers.slice(0,3)??[])];return rows.length?<div className="divider-list">{rows.map((r,i)=><div key={`${r.symbol}-${i}`} className="flex items-center justify-between py-2"><Link href={`/companies/${r.symbol}`} className="font-bold">{r.symbol}</Link><span className="data-font text-xs">PKR {Number(r.close).toFixed(2)}</span><span className={`data-font text-xs font-semibold ${Number(r.change_percent)>=0?"positive":"negative"}`}>{pct(r.change_percent)}</span></div>)}</div>:<Missing text="Market mover data is unavailable."/>}
  if(id==="alerts"){const flags=data.risk?.flags??[],alerts=data.alerts;return flags.length||alerts.length?<div className="divider-list">{flags.slice(0,5).map((f,i)=><div className="flex gap-3 py-2" key={`${f.code}-${i}`}><span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${f.severity==="high"||f.severity==="critical"?"bg-[#b9473c]":"bg-[#a86f18]"}`}/><div><p className="text-xs font-semibold">{f.code.replaceAll("_"," ")}</p><p className="mt-1 text-[11px] text-muted">{f.message}</p></div></div>)}{alerts.slice(0,Math.max(0,5-flags.length)).map((alert,i)=><div className="flex gap-3 py-2" key={String(alert.id??i)}><span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[#a86f18]"/><div><p className="text-xs font-semibold">{String(alert.classification)==="mandate_breach"?"Mandate breach":"Monitoring warning"}</p><p className="mt-1 text-[11px] text-muted">{String(alert.message??"Alert details unavailable")}</p></div></div>)}</div>:<div className="empty-state"><Icon name="check" size={25}/><strong>No active portfolio exceptions</strong><span>Risk checks and monitoring have not raised a warning.</span></div>}
  if(id==="macro")return <Missing text="No structured macro observations are exposed by the current API."/>;
  if(id==="watchlist")return <Missing text="Watchlist data is not available from the current API."/>;
  if(id==="events")return <Missing text="No upcoming structured events are available."/>;
  return null;
}
function Missing({text}:{text:string}){return <div className="empty-state"><span className="badge">Data needed</span><span>{text}</span></div>}
