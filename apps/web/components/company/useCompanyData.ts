"use client";
import { useEffect, useState } from "react";
import { getCompanyDetail, getCompanyHistory, getCompanyResearch, getCompanyCompleteness, getPortfolios, getDocuments,
  getContextRefresh, deactivateContextRefresh, type ApiDocument, type CompanyDetail, type CompanyResearch, type CompanyCompleteness, type MarketPrice, type Portfolio } from "@/lib/api";
import { getCompanyIntelligence, type CompanyIntelligence } from "@/lib/api/research";

export function useCompanyData(symbol: string) {
  const [detail,setDetail]=useState<CompanyDetail|null>(null), [research,setResearch]=useState<CompanyResearch|null>(null);
  const [history,setHistory]=useState<MarketPrice[]>([]);
  const [portfolios,setPortfolios]=useState<Portfolio[]>([]);
  const [portfolioId,setPortfolioId]=useState("");
  const [portfolioContext,setPortfolioContext]=useState<CompanyResearch|null>(null);
  const [intelligence,setIntelligence]=useState<CompanyIntelligence|null>(null);
  const [coverage,setCoverage]=useState<CompanyCompleteness|null>(null);
  const [documents,setDocuments]=useState<ApiDocument[]>([]);
  const [errors,setErrors]=useState<Record<string,string>>({});
  const [loaded,setLoaded]=useState<Record<string,boolean>>({});
  useEffect(()=>{
    let active=true;
    async function read<T>(key:string,fn:()=>Promise<T>,setter:(value:T)=>void){
      try { const value=await fn(); if(active) setter(value); }
      catch(error){if(active)setErrors(old=>({...old,[key]:error instanceof Error?error.message:"Unavailable"}));}
      finally {if(active)setLoaded(old=>({...old,[key]:true}));}
    }
    void read("history",()=>getCompanyHistory(symbol,2000),setHistory);
    void read("company",()=>getCompanyDetail(symbol),setDetail);
    void read("research",()=>getCompanyResearch(symbol,{displayOnly:true}),setResearch);
    void read("intelligence",()=>getCompanyIntelligence(symbol),setIntelligence);
    void read("documents",()=>getDocuments(symbol),setDocuments);
    void read("coverage",()=>getCompanyCompleteness(symbol),setCoverage);
    const portfoliosChanged=()=>void read("portfolios",getPortfolios,rows=>{
      const owned=rows.filter(row=>!row.archived_at);setPortfolios(owned);setPortfolioId(owned.find(row=>row.is_default)?.id??"");
    });
    portfoliosChanged();window.addEventListener("psx-portfolio-change",portfoliosChanged);
    const refreshQuote=()=>{if(document.hidden)return;void read("company",()=>getCompanyDetail(symbol),setDetail);};
    const quoteTimer=setInterval(refreshQuote,3600000);
    document.addEventListener("visibilitychange",refreshQuote);
    return()=>{active=false;clearInterval(quoteTimer);document.removeEventListener("visibilitychange",refreshQuote);window.removeEventListener("psx-portfolio-change",portfoliosChanged);};
  },[symbol]);
  useEffect(()=>{
    let active=true;setPortfolioContext(null);
    setErrors(old=>{const next={...old};delete next.portfolio;return next;});
    if(portfolioId) void getCompanyResearch(symbol,{portfolioId,displayOnly:true}).then(value=>{if(active)setPortfolioContext(value);})
      .catch(error=>{if(active)setErrors(old=>({...old,portfolio:error.message}));});
    return()=>{active=false;};
  },[symbol,portfolioId]);
  useEffect(()=>{
    const id=research?.refresh_request_id;if(!id)return;
    let active=true;let timer:ReturnType<typeof setTimeout>|undefined;
    const poll=async()=>{try{const result=await getContextRefresh(id);if(!active)return;
      if(result.status==="rebuilt"&&result.result){setResearch(result.result);return;}
      timer=setTimeout(()=>void poll(),10000);
    }catch{if(active)timer=setTimeout(()=>void poll(),10000);}};
    void poll();return()=>{active=false;if(timer)clearTimeout(timer);void deactivateContextRefresh(id).catch(()=>undefined);};
  },[research?.refresh_request_id]);
  return {detail,research,history,portfolios,portfolioId,setPortfolioId,portfolioContext,intelligence,documents,coverage,errors,loaded};
}
