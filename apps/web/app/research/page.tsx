"use client";

import { FormEvent,useEffect,useState } from "react";
import Link from "next/link";
import { Icon } from "@/components/Icon";
import { ApiDocument,RagSearchResponse,getDocuments,searchInstruments,searchRag } from "@/lib/api";

const filters=["All evidence","Companies","Reports","Announcements","Macro","Events"];
const isDemoSource=(url?:string|null)=>Boolean(url?.startsWith("demo://"));
const filterTypes:Record<string,string[]|undefined>={
  "All evidence":undefined,
  Companies:["synthetic_demo_facts","annual_report","quarterly_report","announcement"],
  Reports:["synthetic_demo_facts","annual_report","quarterly_report"],
  Announcements:["announcement"],
  Macro:["macro_brief","macro_report"],
  Events:["announcement","event_brief"],
};
const filterHelp:Record<string,string>={
  "All evidence":"Search every ownership-visible document.",Companies:"Company-linked filings, demo facts and announcements.",Reports:"Annual, quarterly and synthetic demo reports.",Announcements:"Company announcements only.",Macro:"Macro briefs without a company symbol.",Events:"Event briefs and announcements."};

export default function ResearchPage(){
  const [query,setQuery]=useState("");const [filter,setFilter]=useState("All evidence");const [result,setResult]=useState<RagSearchResponse|null>(null);const [docs,setDocs]=useState<ApiDocument[]>([]);const [loading,setLoading]=useState(false);const [error,setError]=useState("");const [showLibrary,setShowLibrary]=useState(true);
  const [scopeSymbol,setScopeSymbol]=useState<string|null>(null);const [scopeStatus,setScopeStatus]=useState<"idle"|"resolving"|"resolved"|"not_found">("idle");
  useEffect(()=>{
    void getDocuments().then(setDocs).catch((e:Error)=>setError(e.message));
    const requested=new URLSearchParams(location.search).get("symbol");
    if(!requested)return;
    setScopeStatus("resolving");
    void searchInstruments(requested).then(matches=>{
      const match=matches.find(item=>item.symbol.toUpperCase()===requested.toUpperCase());
      if(match){setScopeSymbol(match.symbol);setScopeStatus("resolved")}else setScopeStatus("not_found");
    }).catch(()=>setScopeStatus("not_found"));
  },[]);
  async function submit(e:FormEvent){e.preventDefault();setLoading(true);setError("");try{setResult(await searchRag({query,limit:12,symbols:scopeSymbol&&filter!=="Macro"?[scopeSymbol]:undefined,document_types:filterTypes[filter]}))}catch(err){setError(err instanceof Error?err.message:"Search failed")}finally{setLoading(false)}}
  return <div className="page-wrap">
    <header className="page-heading"><div><p className="eyebrow">Evidence discovery</p><h1 className="page-title">Research</h1><p className="page-subtitle">Search narrative evidence across filings and reports. Exact numerical values remain database queries.</p></div><button className="btn btn-secondary" onClick={()=>setShowLibrary(!showLibrary)}><Icon name="settings"/>{showLibrary?"Hide library":"Show library"}</button></header>
    {scopeStatus==="not_found"?<div className="notice notice-warn mt-4" role="alert"><Icon name="warning"/><span>The requested symbol was not found in the instrument catalog. Showing market-wide search.</span></div>:null}
    {scopeSymbol?<div className="mt-4 flex items-center gap-2"><span className="badge badge-good">Scoped to {scopeSymbol}</span><button type="button" className="text-[11px] font-semibold text-accent" onClick={()=>{setScopeSymbol(null);setScopeStatus("idle")}}>Remove company scope</button></div>:null}
    <form onSubmit={submit} className="source-rail p-5"><div className="flex flex-col gap-2 sm:flex-row"><label className="relative flex-1"><span className="sr-only">Research query</span><input className="field min-h-12 pl-10 text-sm" value={query} onChange={e=>setQuery(e.target.value)} placeholder={scopeSymbol?`Search within ${scopeSymbol}`:"Search a company, filing topic, policy or event"} required/><Icon name="search" className="absolute left-3 top-3.5 text-muted"/></label><button className="btn btn-primary min-h-12 px-5">{loading?"Searching evidence…":"Search evidence"}</button></div><div className="mt-4 flex gap-1 overflow-x-auto" role="tablist" aria-label="Evidence type">{filters.map(f=><button type="button" key={f} className="segment shrink-0" aria-selected={filter===f} onClick={()=>setFilter(f)}>{f}</button>)}</div><p className="mt-2 text-[11px] text-muted">{filterHelp[filter]} The selected tab is sent as a retrieval filter on the next search.</p></form>
    {error?<div className="notice notice-error mt-4" role="alert"><Icon name="warning"/>{error}</div>:null}
    {result?<div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1fr)_280px]"><section className="grid content-start gap-3"><div className="flex items-center justify-between"><h2 className="text-[14px] font-semibold">Evidence results</h2><span className="text-[11px] text-muted">{result.chunks.length} cited passages</span></div>{result.chunks.length?result.chunks.map((c,i)=><article className="panel p-5" key={c.id}><div className="flex flex-wrap items-center justify-between gap-2"><span className="text-[11px] font-semibold text-accent">Evidence {i+1}</span><span className="data-font text-[11px] text-muted">Relevance {c.score.toFixed(3)}</span></div><h3 className="mt-3 text-[15px] font-semibold">{c.citation.title}</h3><p className="mt-2 text-[13px] leading-6 text-[#3f454b]">{c.chunk_text}</p><div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3 text-[11px] text-muted"><span>{c.citation.source_name} · {c.page_number?`Page ${c.page_number}`:"Page unavailable"}</span>{c.citation.source_url&&!isDemoSource(c.citation.source_url)?<a href={c.citation.source_url} target="_blank" rel="noreferrer" className="font-semibold text-accent">Open source</a>:c.citation.source_url?<span className="font-semibold">Synthetic demo source</span>:null}</div></article>):<Empty title="No cited passages found" text={scopeSymbol?`No evidence above the relevance threshold was found for ${scopeSymbol}. Try a narrower query.`:"Try a narrower query or remove document filters."}/>}</section><aside className="h-fit xl:sticky xl:top-20"><details className="panel"><summary className="cursor-pointer px-4 py-3 text-[12px] font-semibold">Search audit</summary><div className="space-y-4 border-t border-line p-4"><Audit label="Scope" value={scopeSymbol?`${filter} · ${scopeSymbol}`:filter}/><Audit label="Query" value={query}/><Audit label="Citations" value={String(result.citations.length)}/><Audit label="Exact values" value="Not sourced from RAG"/></div></details></aside></div>:<div className="mt-5 grid gap-3 md:grid-cols-3"><Prompt title="Company evidence" text="What changed in MEBL’s deposit mix?" onClick={()=>setQuery("MEBL deposit mix change")}/><Prompt title="Policy transmission" text="Which sectors are exposed to rate changes?" onClick={()=>setQuery("interest rate sector impact")}/><Prompt title="Management outlook" text="Find cited forward-looking commentary." onClick={()=>setQuery("management outlook and planned investment")}/></div>}
    {showLibrary?<section className="panel mt-5"><div className="panel-head"><div><h2 className="panel-title">Evidence library</h2><p className="mt-1 text-[11px] text-muted">Rows come from ingested documents. Demo rows are synthetic; live rows persist when an upload or connector creates a document and searchable chunks.</p></div><Link href="/documents" className="text-[12px] font-semibold text-accent">Manage documents</Link></div>{docs.length?<div className="table-wrap"><table className="data-table"><thead><tr><th>Document</th><th>Company</th><th>Type</th><th>Source</th><th>Status</th><th>Published</th></tr></thead><tbody>{docs.slice(0,12).map(d=><tr key={d.id}><td className="font-semibold">{d.title}</td><td>{d.symbol??"—"}</td><td>{d.document_type.replaceAll("_"," ")}</td><td>{d.source_name}{isDemoSource(d.source_url)?" · synthetic":""}</td><td><span className={`badge ${d.status==="ready"?"badge-good":""}`}>{d.status}</span></td><td>{d.published_date??"—"}</td></tr>)}</tbody></table></div>:<Empty title="Evidence library is empty" text="Upload reports and announcements to enable cited retrieval."/>}</section>:null}
  </div>;
}

function Empty({title,text}:{title:string;text:string}){return <div className="panel empty-state"><strong>{title}</strong><span>{text}</span></div>}
function Prompt({title,text,onClick}:{title:string;text:string;onClick:()=>void}){return <button onClick={onClick} className="rounded-xl bg-surface p-5 text-left transition-colors hover:bg-[#e8eae6]"><span className="eyebrow">{title}</span><p className="mt-2 text-[13px] font-semibold leading-5">{text}</p></button>}
function Audit({label,value}:{label:string;value:string}){return <div><p className="metric-label">{label}</p><p className="mt-1 text-xs font-semibold">{value}</p></div>}
