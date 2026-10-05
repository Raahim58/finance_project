"use client";
import {useEffect,useState} from "react";
import {CompanyDigest,getCompanyDigest,retryCompanyDigest,DigestClaim} from "@/lib/api/research";

export function CompanyDigestPanel({symbol}:{symbol:string}){
  const [digest,setDigest]=useState<CompanyDigest|null>(null);
  const [error,setError]=useState("");
  const [revision,setRevision]=useState(0);
  const [retrying,setRetrying]=useState(false);
  useEffect(()=>{
    let active=true;
    let timer:ReturnType<typeof setTimeout>|undefined;
    setDigest(null);setError("");
    async function load(first:boolean){
      try{
        const value=await getCompanyDigest(symbol,first);
        if(!active)return;
        setDigest(value);setError("");
        if(["queued","running"].includes(value.status))timer=setTimeout(()=>void load(false),3000);
      }catch(e){if(active)setError(e instanceof Error?e.message:"Company brief unavailable")}
    }
    void load(true);
    return()=>{active=false;if(timer)clearTimeout(timer)};
  },[symbol,revision]);
  async function retry(){
    setRetrying(true);
    try{await retryCompanyDigest(symbol);setRevision(v=>v+1)}
    catch(e){setError(e instanceof Error?e.message:"Refresh failed")}
    finally{setRetrying(false)}
  }
  function claim(row:DigestClaim,index:number){
    const sources=row.refs.flatMap(ref=>digest?.brief_sources[ref]??[]);
    const unique=Array.from(new Map(sources.map(s=>[JSON.stringify(s),s])).values());
    return <li className="mt-2 text-sm leading-6" key={index}>{row.text}<span className="ml-2 text-[11px] text-muted">{row.kind.replaceAll("_"," ")}</span>{unique.map((s,i)=>s.source_url?<a className="ml-2 text-xs text-accent underline" key={i} href={s.source_url} target="_blank" rel="noreferrer">{s.title??s.source_name??"Source"}{s.page_number?` · p${s.page_number}`:""}</a>:<span className="ml-2 text-xs text-muted" key={i}>{s.title??s.source_name??"Source"} · source link unavailable</span>)}</li>;
  }
  return <section className="panel mt-4" aria-label="Company brief"><div className="panel-head"><h2 className="panel-title">Company brief</h2>{digest?.generated_at?<span className="text-xs text-muted">Updated {new Date(digest.generated_at).toLocaleString("en-PK")}</span>:null}</div><div className="p-5">
    {error?<p role="alert" className="text-sm">{error}</p>:null}
    {!digest&&!error?<p className="text-sm text-muted">Loading saved company brief…</p>:null}
    {digest&&!digest.current?<p className="mb-3 text-sm text-muted">{["queued","running"].includes(digest.status)?digest.brief?"Showing previous brief while updated evidence is prepared.":"Preparing company brief…":digest.status==="provider_unavailable"?"Save an AI provider key to prepare the company brief.":"Company brief could not be refreshed. Previous evidence is preserved."}</p>:null}
    {digest?.brief?([['thesis','Thesis'],['earnings_drivers','Earnings drivers'],['valuation','Valuation context'],['catalysts','Catalysts'],['risks','Risks']] as const).map(([key,label])=>digest.brief![key].length?<div key={key} className="mb-4"><h3 className="text-sm font-semibold">{label}</h3><ul>{digest.brief![key].map(claim)}</ul></div>:null):null}
    {digest?.brief?.unresolved_questions.length?<div><h3 className="text-sm font-semibold">Open questions</h3><ul className="mt-2 text-sm text-muted">{digest.brief.unresolved_questions.map((text,i)=><li key={i}>{text}</li>)}</ul></div>:null}
    {digest&&["failed","uncertain","budget_exhausted"].includes(digest.status)?<button className="btn btn-secondary mt-3" disabled={retrying} onClick={()=>void retry()}>Retry brief</button>:null}
    {digest?.snapshot?.missing_data.length?<p className="mt-3 text-xs text-muted">Some underlying evidence is missing or incomplete. The brief covers available stored evidence.</p>:null}
  </div></section>;
}
