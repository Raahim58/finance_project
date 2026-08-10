"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { Portfolio,getPortfolios } from "@/lib/api";

const tabs:Array<[string,string]>=[["overview","Overview"],["build","Build"],["quant","Quant"],["risk","Risk"],["stress","Stress"],["research","Research"],["activity","Activity"],["settings","IPS"]];

export function PortfolioWorkspace({portfolioId,active,children}:{portfolioId:string;active:string;children:React.ReactNode}){
  const [portfolios,setPortfolios]=useState<Portfolio[]>([]);
  useEffect(()=>{void getPortfolios().then(setPortfolios)},[]);
  const selected=portfolios.find(p=>p.id===portfolioId);
  return <div className="page-wrap">
    <header className="page-heading"><div><p className="eyebrow">Portfolio workspace</p><h1 className="page-title">{selected?.name??"Portfolio"}</h1><p className="page-subtitle">{selected?.goal_summary||"Mandate goal has not been defined."}</p></div><label className="field-label w-full sm:w-64"><span className="sr-only">Select portfolio</span><select className="field" value={portfolioId} onChange={e=>{location.href=`/portfolios/${e.target.value}/${active}`}}>{portfolios.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label></header>
    <nav aria-label="Portfolio sections" className="mb-4 flex overflow-x-auto border border-line bg-white p-1">
      {tabs.map(([id,label])=><Link key={id} href={`/portfolios/${portfolioId}/${id}` as never} aria-current={active===id?"page":undefined} className={`flex min-h-8 shrink-0 items-center gap-1.5 border-b-2 px-3 text-[11px] font-semibold ${active===id?"border-[#17324d] bg-[#edf2f6] text-[#17324d]":"border-transparent text-muted hover:bg-[#f4f6f7]"}`}>{label}{active===id?<Icon name="chevron" size={12}/>:null}</Link>)}
    </nav>
    {children}
  </div>;
}
