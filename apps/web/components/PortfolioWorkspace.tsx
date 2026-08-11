"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Portfolio,getPortfolios } from "@/lib/api";

const tabs:Array<[string,string,string?]>=[["overview","Overview"],["build","Build"],["quant","Quant"],["risk","Risk"],["stress","Scenarios","scenarios"],["research","Research"],["activity","Activity"],["settings","IPS","ips"]];

export function PortfolioWorkspace({portfolioId,active,children}:{portfolioId:string;active:string;children:React.ReactNode}){
  const [portfolios,setPortfolios]=useState<Portfolio[]>([]);
  useEffect(()=>{let active=true;void getPortfolios().then(rows=>active&&setPortfolios(rows)).catch(()=>active&&setPortfolios([]));return()=>{active=false}},[]);
  const selected=portfolios.find(p=>p.id===portfolioId);
  return <div className="page-wrap">
    <header className="page-heading">
      <div>
        <div className="mb-2 flex flex-wrap items-center gap-2"><p className="eyebrow">Portfolio workspace</p>{selected?.archived_at?<span className="badge">Archived</span>:<span className="badge badge-good">Active mandate</span>}</div>
        <h1 className="page-title">{selected?.name??"Portfolio"}</h1>
        <p className="page-subtitle">{selected?.goal_summary||"Mandate goal has not been defined."}</p>
      </div>
      <label className="field-label w-full sm:w-72"><span>Portfolio scope</span><select className="field" value={portfolioId} onChange={e=>{location.href=`/portfolios/${e.target.value}/${active}`}}>{portfolios.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
    </header>
    <nav aria-label="Portfolio sections" className="mb-7 flex overflow-x-auto border-b border-line">
      {tabs.map(([id,label,path])=><Link key={id} href={`/portfolios/${portfolioId}/${path??id}` as never} aria-current={active===id?"page":undefined} className={`relative flex min-h-11 shrink-0 items-center px-3 text-[13px] font-semibold transition-colors after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full ${active===id?"text-accent after:bg-accent":"text-muted after:bg-transparent hover:text-ink"}`}>{label}</Link>)}
    </nav>
    {children}
  </div>;
}
