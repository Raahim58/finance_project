"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Icon } from "@/components/Icon";
import { Portfolio, getPortfolios } from "@/lib/api";
import styles from "@/components/portfolio/portfolio.module.css";


/** Tabs live in the app top bar (PortfolioTabs); the portfolio is chosen from the top-right picker. */
export function PortfolioWorkspace({portfolioId,active,children}:{portfolioId:string;active:string;children:React.ReactNode}){
  const router=useRouter();
  const [portfolios,setPortfolios]=useState<Portfolio[]>([]);
  const [loaded,setLoaded]=useState(false);
  useEffect(()=>{let live=true;void getPortfolios().then(rows=>{if(live){setPortfolios(rows);setLoaded(true)}}).catch(()=>{if(live){setPortfolios([]);setLoaded(true)}});return()=>{live=false}},[]);
  const fallback=useMemo(()=>portfolios.find(p=>p.is_default&&!p.archived_at),[portfolios]);
  const invalidScope=loaded&&!portfolios.some(p=>p.id===portfolioId);
  useEffect(()=>{if(invalidScope&&fallback)router.replace(`/portfolios/${fallback.id}/${active==="stress"?"scenarios":active==="settings"?"ips":active}` as never)},[invalidScope,fallback,active,router]);
  if(invalidScope){
    return <div className={styles.page}><div className="notice notice-warn" role="alert"><Icon name="warning"/><span>{fallback?`This portfolio no longer exists or is not visible to your account. Switching to ${fallback.name}.`:"This portfolio no longer exists or is not visible to your account, and no other portfolio is available."}</span></div></div>;
  }
  return <div data-portfolio-tab={active} className={styles.page}>{children}</div>;
}
