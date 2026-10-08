"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "@/components/Icon";
import { Portfolio, clearApiCache, getIndexHistory, getMarketFreshness, getMarketOverview, getPortfolios, selectDefaultPortfolio, type MarketFreshness, type MarketOverview } from "@/lib/api";
import { formatPercent, numeric } from "@/lib/overview";
import { indexLatest } from "@/lib/markets";
import styles from "@/components/portfolio/portfolio.module.css";

const tabs:Array<[string,string,string?]>=[["overview","Overview"],["settings","IPS","ips"],["build","Build"],["quant","Quant"],["risk","Risk"],["stress","Scenarios","scenarios"],["research","Research"],["activity","Activity"]];

export function PortfolioWorkspace({portfolioId,active,children}:{portfolioId:string;active:string;children:React.ReactNode}){
  const router=useRouter();
  const compact=["overview","quant","research","activity","settings","build"].includes(active);
  const [portfolios,setPortfolios]=useState<Portfolio[]>([]);
  const [portfoliosLoaded,setPortfoliosLoaded]=useState(false);
  const [open,setOpen]=useState(false);
  const [switching,setSwitching]=useState(false);
  const [switchError,setSwitchError]=useState("");
  const [pulse,setPulse]=useState<{overview:MarketOverview|null;freshness:MarketFreshness|null;history:Awaited<ReturnType<typeof getIndexHistory>>}>({overview:null,freshness:null,history:[]});
  const menuRef=useRef<HTMLDivElement>(null);
  useEffect(()=>{let live=true;void getPortfolios().then(rows=>{if(live){setPortfolios(rows);setPortfoliosLoaded(true)}}).catch(()=>{if(live){setPortfolios([]);setPortfoliosLoaded(true)}});return()=>{live=false}},[]);
  useEffect(()=>{if(compact)return;let live=true;void Promise.all([getMarketOverview().catch(()=>null),getMarketFreshness().catch(()=>null),getIndexHistory("KSE-100",5).catch(()=>[])]).then(([overview,freshness,history])=>{if(live)setPulse({overview,freshness,history})});return()=>{live=false}},[compact]);
  useEffect(()=>{
    if(!open)return;
    const close=(event:MouseEvent|KeyboardEvent)=>{if(event instanceof KeyboardEvent){if(event.key==="Escape")setOpen(false);return}if(menuRef.current&&!menuRef.current.contains(event.target as Node))setOpen(false)};
    document.addEventListener("mousedown",close);document.addEventListener("keydown",close);
    return()=>{document.removeEventListener("mousedown",close);document.removeEventListener("keydown",close)};
  },[open]);
  const available=useMemo(()=>portfolios.filter(p=>!p.archived_at),[portfolios]);
  const selected=portfolios.find(p=>p.id===portfolioId);
  const invalidScope=portfoliosLoaded&&!selected;
  const fallback=available.find(p=>p.is_default);
  useEffect(()=>{if(invalidScope&&fallback)router.replace(`/portfolios/${fallback.id}/${active==="stress"?"scenarios":active==="settings"?"ips":active}` as never)},[invalidScope,fallback,active,router]);
  if(invalidScope){
    return <div className={styles.page}><div className="notice notice-warn" role="alert"><Icon name="warning"/><span>{fallback?`This portfolio no longer exists or is not visible to your account. Switching to ${fallback.name}.`:"This portfolio no longer exists or is not visible to your account, and no other portfolio is available."}</span></div></div>;
  }
  const path=(id:string)=>`/portfolios/${id}/${tabs.find(([key])=>key===active)?.[2]??active}`;
  async function choose(id:string){
    setOpen(false);if(id===portfolioId)return;
    setSwitching(true);setSwitchError("");
    try{await selectDefaultPortfolio(id);clearApiCache();window.dispatchEvent(new Event("psx-portfolio-change"));router.push(path(id) as never)}
    catch(error){setSwitchError(error instanceof Error?error.message:"Portfolio could not be selected")}
    finally{setSwitching(false)}
  }
  const latest=indexLatest(pulse.history,pulse.overview?.snapshot);
  const date=latest?.date??pulse.freshness?.latest_trade_date;
  const session=pulse.freshness?.exchange_session_status;
  return <div className={`${styles.page}${compact?` ${styles.compact}`:""}`}>
    {!compact?<p className={styles.dateline}>
      <span>{date?new Date(`${date}T00:00:00`).toLocaleDateString("en-GB",{weekday:"short",day:"numeric",month:"short",year:"numeric"}):"Date unavailable"}</span>
      <span>{session?`Market ${session==="unknown"?"session unknown":session}`:"Session unavailable"}</span>
      {latest&&numeric(latest.percent)!=null?<span>{latest.name} <b className={Number(latest.percent)>0?styles.positive:Number(latest.percent)<0?styles.negative:""}>{formatPercent(latest.percent)}</b></span>:null}
    </p>:null}
    <div className={styles.titleRow} ref={menuRef}>
      <button type="button" className={styles.titleButton} aria-haspopup="listbox" aria-expanded={open} onClick={()=>setOpen(value=>!value)} disabled={!portfoliosLoaded||switching}>
        <h1>{selected?.name??(portfoliosLoaded?"Portfolio":"Loading…")}</h1><span aria-hidden="true" className={`${styles.caret} ${open?styles.caretOpen:""}`}><Icon name="chevron" size={22}/></span>
      </button>
      {selected?.archived_at?<span className="badge">Archived</span>:null}
      {open?<div className={styles.menu} role="listbox" aria-label="Select portfolio">
        {available.map(p=><button key={p.id} role="option" aria-selected={p.id===portfolioId} onClick={()=>void choose(p.id)}><span>{p.name}</span>{p.id===portfolioId?<Icon name="check" size={15}/>:p.is_default?<small>Default</small>:null}</button>)}
        <Link href={"/portfolios/manage" as never} onClick={()=>setOpen(false)}>Manage portfolios…</Link>
      </div>:null}
    </div>
    {!compact&&selected?.goal_summary?<p className={styles.goal}>{selected.goal_summary}</p>:null}
    {switchError?<div className="notice notice-error mb-3" role="alert"><Icon name="warning"/><span>{switchError}</span></div>:null}
    <nav aria-label="Portfolio sections" className={styles.tabs}>
      {tabs.map(([id,label,slug])=><Link key={id} href={`/portfolios/${portfolioId}/${slug??id}` as never} aria-current={active===id?"page":undefined}>{label}</Link>)}
    </nav>
    {children}
  </div>;
}
