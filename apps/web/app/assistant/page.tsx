"use client";

import { FormEvent,Suspense,useEffect,useRef,useState } from "react";
import { useSearchParams } from "next/navigation";
import { Icon } from "@/components/Icon";
import { TermHelp } from "@/components/TermHelp";
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
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]"><main className="grid min-w-0 content-start gap-5"><form onSubmit={ask} className="source-rail p-5"><div className="mb-4 flex flex-wrap items-center justify-between gap-3"><h2 className="text-[14px] font-semibold">New research question</h2><label className="field-label w-full sm:w-60"><span className="sr-only">Portfolio scope</span><select aria-label="Portfolio scope" className="field" value={portfolioId} onChange={e=>{scopeTouched.current=true;setPortfolioId(e.target.value)}}><option value="" disabled>No selected portfolio</option>{portfolios.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label></div><label className="field-label">Question<textarea className="field mt-1 text-sm leading-6" rows={5} value={question} onChange={e=>setQuestion(e.target.value)} placeholder="Where is risk concentrated, what changed, and what evidence is still missing?" required/></label><div className="mt-4 flex justify-end"><button className="btn btn-primary" disabled={loading}><Icon name="assistant"/>{loading?"Gathering evidence…":"Analyze question"}</button></div></form>{error?<div className="notice notice-error" role="alert"><Icon name="warning"/>{error}</div>:null}{result?<Response result={result}/>:<div className="rounded-xl bg-surface px-6 py-12 text-center"><Icon name="assistant" size={28} className="mx-auto text-muted"/><strong className="mt-3 block text-[13px]">Ask a portfolio or market question</strong><span className="mt-1 block text-[12px] text-muted">The response will show its evidence boundaries and freshness warnings.</span></div>}</main><aside className="grid h-fit gap-4 xl:sticky xl:top-20"><section className="panel"><div className="panel-head"><h2 className="panel-title">Analysis scope</h2></div><div className="panel-body space-y-4"><Scope label="Portfolio" value={portfolios.find(p=>p.id===portfolioId)?.name??"No selected portfolio"}/><Scope label="Candidate universe" value="Market-wide when requested"/><Scope label="Numerical facts" value="Deterministic services"/><Scope label="Narrative evidence" value="Cited documents"/><Scope label="Portfolio changes" value="Read-only recommendations"/></div></section></aside></div>
  </div>;
}

function Response({result}:{result:AssistantResult}){const mode=result.synthesis?.mode;const llm=mode==="llm_tool_loop"||mode==="llm_grounded";const unavailable=mode==="synthesis_unavailable"||mode==="recommendation_synthesis_unavailable";const status=llm?`AI synthesis · ${result.synthesis.provider} · ${result.synthesis.model}`:unavailable?"Synthesis unavailable":"Deterministic fallback";return <div className="grid gap-5"><section className="source-rail px-6 py-5"><div className="flex flex-wrap items-start justify-between gap-2"><div><div className="flex items-center gap-2"><h2 className="text-[14px] font-semibold">Answer</h2><span className={`badge ${llm?"badge-good":"badge-warn"}`}>{status}</span></div><TokenUsage usage={result.synthesis?.token_usage}/><DiagnosticReference ids={result.synthesis?.diagnostic_ids}/></div><span className="text-[11px] text-muted">{new Date(result.created_at).toLocaleString()}</span></div><AnswerText text={result.answer}/></section><AllocationTable allocation={result.synthesis?.allocation_check}/>{result.calculated_evidence.length?<Evidence title="Key numerical evidence" rows={result.calculated_evidence}/>:null}{result.source_citations.length?<Citations rows={result.source_citations}/>:null}{result.uncertainty.length||result.freshness_warnings.length?<section className="panel"><div className="panel-head"><h2 className="panel-title">Uncertainty and missing data</h2><span className="badge badge-warn">Review</span></div><div className="divider-list">{[...result.uncertainty,...result.freshness_warnings].map((x,i)=><div className="flex gap-3 px-4 py-3 text-[13px]" key={i}><Icon name="warning" size={15} className="mt-0.5 shrink-0 text-[#a86f18]"/><span>{x}</span></div>)}</div></section>:null}{result.tool_trace.length?<details className="panel"><summary className="cursor-pointer px-4 py-3 text-[12px] font-semibold">How this answer was built</summary><p className="border-t border-line px-4 py-3 text-[12px] text-muted">Used {result.tool_trace.length} backend data read{result.tool_trace.length===1?"":"s"}. Numerical portfolio facts came from deterministic services; {llm?"the configured model consolidated and interpreted the retrieved context":unavailable?"model synthesis was unavailable, so only grounded facts were retained":"a deterministic fallback organized the available facts"}.</p></details>:null}</div>}
function TokenUsage({usage}:{usage:AssistantResult["synthesis"]["token_usage"]}){if(!usage)return null;const number=new Intl.NumberFormat("en-US");const cached=usage.cache_read_tokens?` · Cached ${number.format(usage.cache_read_tokens)}`:"";return <p className="data-font mt-2 text-[10px] text-muted">{usage.reported_by_provider?`Input ${number.format(usage.input_tokens)}${cached} · Output ${number.format(usage.output_tokens)} · Total ${number.format(usage.total_tokens)}`:"Token usage unavailable"} · {usage.model_calls} provider call{usage.model_calls===1?"":"s"}</p>}
function DiagnosticReference({ids}:{ids:string[]|undefined}){if(!ids?.length)return null;return <p className="data-font mt-1 text-[10px] text-muted">Diagnostic {ids[0].slice(0,8)}{ids.length>1?` · ${ids.length-1} more`:""}</p>}
function AnswerText({text}:{text:string}){return <p className="mt-4 whitespace-pre-wrap text-[14px] leading-7">{text}</p>}
function AllocationTable({allocation}:{allocation:AssistantResult["synthesis"]["allocation_check"]}) {
  if(!allocation||allocation.status==="not_requested")return null;
  const percent=(value:number|null|undefined)=>value==null?"Unavailable":new Intl.NumberFormat("en-US",{style:"percent",maximumFractionDigits:2}).format(value);
  const goal=allocation.checks?.modeled_goal;
  const goalLabel=goal?.status==="meets"?"Meets modeled goal":goal?.status==="below"?"Below modeled goal":"Modeled goal unavailable";
  return <section className="panel">
    <div className="panel-head"><h2 className="panel-title">Allocation calculation</h2><span className={`badge ${allocation.status==="accepted"?"badge-good":"badge-warn"}`}>Verification: {allocation.status}</span></div>
    <div className="flex flex-wrap gap-2 px-5 py-3 text-[12px]">
      <span>Prices: {allocation.checks?.price_freshness?.status??"unavailable"}</span>
      <span>IPS: {allocation.checks?.ips_compliance?.status??"unavailable"}</span>
      <span>{goalLabel}</span>
    </div>
    {allocation.evidence_readiness?.status==="insufficient_evidence"?<p className="px-5 pb-3 text-[12px] text-muted">Insufficient evidence for an actionable recommendation.</p>:null}
    {allocation.rows?.length?<div className="overflow-x-auto"><table className="w-full text-left text-[12px]">
      <caption className="px-5 py-2 text-left text-muted">Server-calculated capital weights, including cash. Rejected rows are diagnostic results.</caption>
      <thead><tr>{["Holding","Current weight","Proposed weight","Gross trade","Quantity"].map(label=><th className="px-5 py-2" scope="col" key={label}>{label}</th>)}</tr></thead>
      <tbody>{allocation.rows.map(row=><tr className="border-t border-line" key={row.instrument_id}><th className="px-5 py-3" scope="row">{row.symbol}</th><td className="px-5 py-3">{percent(row.current_capital_weight)}</td><td className="px-5 py-3">{percent(row.proposed_capital_weight)}</td><td className="px-5 py-3">{row.side?`${row.side} ${row.currency??""} ${row.gross_amount??"Unavailable"}`:"—"}</td><td className="px-5 py-3">{row.quantity??"—"}</td></tr>)}</tbody>
    </table></div>:null}
    {goal?<p className="px-5 py-3 text-[12px] text-muted">Required return: {percent(goal.required_return)} · Proposed modeled return: {percent(goal.proposed_modeled_return)} · Shortfall: {percent(goal.shortfall)}{goal.method?` · Method: ${goal.method}`:""}. Modeled estimates do not guarantee returns.</p>:null}
    {allocation.errors?.length?<p className="px-5 py-3 text-[12px]">{allocation.errors.join(", ")}</p>:null}
    {allocation.cost_note?<p className="px-5 py-3 text-[12px] text-muted">{allocation.cost_note}</p>:null}
    {allocation.verification_id?<p className="data-font px-5 pb-3 text-[10px] text-muted">Verification {allocation.verification_id}</p>:null}
  </section>;
}

function Evidence({title,rows}:{title:string;rows:Array<Record<string,unknown>>}){return <section className="panel"><div className="panel-head"><h2 className="panel-title">{title}</h2><span className="text-[11px] text-muted">{rows.length} item{rows.length===1?"":"s"}</span></div><div className="divider-list">{rows.map((r,i)=><div className="px-5 py-4" key={i}><DataRecord value={r}/></div>)}</div></section>}
function Citations({rows}:{rows:Array<Record<string,unknown>>}){return <section className="panel"><div className="panel-head"><h2 className="panel-title">Cited evidence</h2><span className="text-[11px] text-muted">{rows.length} source{rows.length===1?"":"s"}</span></div><div className="divider-list">{rows.map((row,index)=>{const url=typeof row.source_url==="string"&&/^https?:\/\//.test(row.source_url)?row.source_url:null;return <article className="px-5 py-4" key={String(row.id??index)}><div className="flex flex-wrap items-center gap-2">{url?<a className="text-[13px] font-semibold underline" href={url} target="_blank" rel="noreferrer">{String(row.title||row.source_name||"Source unavailable")}</a>:<strong className="text-[13px]">{String(row.title||row.source_name||"Source unavailable")}</strong>}{row.symbol?<span className="badge">{String(row.symbol)}</span>:null}</div>{row.quote_snippet?<p className="mt-2 text-[12px] leading-5 text-muted">{String(row.quote_snippet)}</p>:null}<p className="mt-2 text-[11px] text-muted">{String(row.source_name??"Source unavailable")}{row.page_number?` · page ${String(row.page_number)}`:""}</p></article>})}</div></section>}
function DataRecord({value}:{value:Record<string,unknown>}){const hidden=new Set(["evidence_id","chunk_id","document_id","run_id","unit"]);return <dl className="grid gap-x-5 gap-y-2 sm:grid-cols-[150px_1fr]">{Object.entries(value).filter(([k,v])=>!hidden.has(k)&&v!==null&&v!==undefined).map(([k,v])=>{const formatted=formatEvidence(k,v,value.unit);return <div className="contents" key={k}><dt className="text-[11px] font-semibold capitalize text-muted">{k.replaceAll("_"," ")}</dt><dd className="m-0 break-words text-[12px] leading-5"><span className="inline-flex items-center gap-1">{formatted}{k==="metric"?<TermHelp term={formatted}/>:null}</span></dd></div>})}</dl>}
function formatEvidence(key:string,value:unknown,unit:unknown){const labels:Record<string,string>={current_weight:"Current portfolio weight",sector_headroom:"Sector headroom",average_holding_correlation:"Average holding correlation",annual_volatility:"Annual volatility",macro_regime:"Macro regime",percentage_risk_contribution:"Risk contribution"};if(key==="metric")return labels[String(value)]??String(value).replaceAll("_"," ");if(typeof value==="number"&&(key==="value"||key==="limit")){if(unit==="decimal"||unit==="percentage_point")return `${(value*100).toFixed(2)}%`;if(unit==="PKR")return `PKR ${new Intl.NumberFormat("en-PK",{maximumFractionDigits:0}).format(value)}`;return new Intl.NumberFormat("en-PK",{maximumFractionDigits:3}).format(value)}if(typeof value==="object")return Array.isArray(value)?value.map(String).join(", "):Object.entries(value as Record<string,unknown>).map(([a,b])=>`${a.replaceAll("_"," ")}: ${String(b)}`).join(" · ");return String(value).replaceAll("_"," ")}
function Scope({label,value}:{label:string;value:string}){return <div><p className="metric-label">{label}</p><p className="mt-1 text-[12px] font-semibold">{value}</p></div>}
