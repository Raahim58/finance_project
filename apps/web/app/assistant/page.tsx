"use client";

import { FormEvent,Suspense,useEffect,useRef,useState } from "react";
import { useSearchParams } from "next/navigation";
import { Icon } from "@/components/Icon";
import { AssistantResponse } from "@/components/AssistantResponse";
import { AssistantResult,Portfolio,deactivateContextRefresh,getPortfolios,sendAssistantMessage,activeAssistantExecution,resumeAssistantExecution,acknowledgeAssistantExecution } from "@/lib/api";

export default function AssistantPage(){return <Suspense fallback={<div className="page-wrap"><div className="panel h-96 skeleton"/></div>}><AssistantContent/></Suspense>}
function AssistantContent(){
  const params=useSearchParams();const instrumentId=params?.get("instrument_id")??"";const [portfolios,setPortfolios]=useState<Portfolio[]>([]);const [portfolioId,setPortfolioId]=useState(params?.get("portfolio_id")??"");const [question,setQuestion]=useState(params?.get("question")??"");const [result,setResult]=useState<AssistantResult|null>(null);const [loading,setLoading]=useState(false);const [error,setError]=useState("");
  // Portfolio identity comes from trusted UI state. Once the user touches the selector,
  // an asynchronous list response must not replace that choice.
  const requestSeq=useRef(0);
  const scopeTouched=useRef(false);
  useEffect(()=>{const id=result?.synthesis.execution_id;if(id)void acknowledgeAssistantExecution(id).catch(()=>undefined)},[result]);
  useEffect(()=>{
    const active=activeAssistantExecution();if(!active)return;
    const id=++requestSeq.current;let mounted=true;
    setLoading(true);
    void resumeAssistantExecution(active).then(response=>{if(mounted&&id===requestSeq.current)setResult(response)})
      .catch((err:unknown)=>{if(mounted)setError(err instanceof Error?err.message:"Assistant recovery failed")})
      .finally(()=>{if(mounted&&id===requestSeq.current)setLoading(false)});
    return()=>{mounted=false};
  },[]);
  useEffect(()=>{void getPortfolios().then(rows=>{setPortfolios(rows);if(!params?.get("portfolio_id")&&!scopeTouched.current){setPortfolioId(rows.find(row=>row.is_default)?.id??"")}}).catch((reason:unknown)=>setError(reason instanceof Error?`Portfolio scope request failed: ${reason.message}`:"Portfolio scope request failed"))},[params]);
  useEffect(()=>{const refreshId=result?.refresh_request_id;if(!refreshId)return;return()=>{void deactivateContextRefresh(refreshId).catch(()=>undefined)}},[result?.refresh_request_id]);
  async function ask(e:FormEvent){
    e.preventDefault();
    const askedQuestion=question;const askedPortfolioId=portfolioId;
    const id=++requestSeq.current;
    setLoading(true);setError("");
    try{
      const response=await sendAssistantMessage(askedQuestion,askedPortfolioId||undefined,instrumentId||undefined);
      if(id===requestSeq.current) setResult(response);
    }catch(err){
      if(id===requestSeq.current) setError(err instanceof Error?err.message:"Assistant failed");
    }finally{
      if(id===requestSeq.current) setLoading(false);
    }
  }
  return <div className="page-wrap">
    <header className="page-heading"><div><p className="eyebrow">Portfolio and market research</p><h1 className="page-title">Research assistant</h1><p className="page-subtitle">Ask about a security, your portfolio, risks, or the evidence behind a view.</p></div></header>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]"><main className="grid min-w-0 content-start gap-5"><form onSubmit={ask} className="source-rail p-5"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h2 className="text-[14px] font-semibold">New research question</h2><label className="field-label w-full sm:w-60"><span className="sr-only">Portfolio scope</span><select aria-label="Portfolio scope" className="field" value={portfolioId} onChange={e=>{scopeTouched.current=true;setPortfolioId(e.target.value)}}><option value="" disabled>No selected portfolio</option>{portfolios.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label></div><label className="field-label">Question<textarea className="field mt-1 text-sm leading-6" rows={5} value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Where is risk concentrated, what changed, and what evidence is still missing?" required/></label><div className="mt-4 flex justify-end"><button className="btn btn-primary" disabled={loading}><Icon name="assistant"/>{loading?"Gathering evidence…":"Analyze question"}</button></div></form>{error?<div className="notice notice-error" role="alert"><Icon name="warning"/>{error}</div>:null}{result?<AssistantResponse result={result}/>:<div className="rounded-xl bg-surface px-6 py-12 text-center"><Icon name="assistant" size={28} className="mx-auto text-muted"/><strong className="mt-3 block text-[13px]">Ask a portfolio or market question</strong><span className="mt-1 block text-[12px] text-muted">The response will show its evidence boundaries and freshness warnings.</span></div>}</main><aside className="grid h-fit gap-4 xl:sticky xl:top-20"><section className="panel"><div className="panel-head"><h2 className="panel-title">Analysis scope</h2></div><div className="panel-body space-y-4"><Scope label="Portfolio" value={portfolios.find(p=>p.id===portfolioId)?.name??"No selected portfolio"}/><Scope label="Candidate universe" value="Market-wide when requested"/><Scope label="Numerical facts" value="Deterministic services"/><Scope label="Narrative evidence" value="Cited documents"/><Scope label="Portfolio changes" value="Read-only recommendations"/></div></section></aside></div>
  </div>;
}

function Scope({label,value}:{label:string;value:string}){return <div><p className="metric-label">{label}</p><p className="mt-1 text-[12px] font-semibold">{value}</p></div>}
