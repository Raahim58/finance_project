"use client";
import Link from "next/link";
import { useEffect,useState } from "react";
import { getPortfolioSummary,getIpsCompliance,type PortfolioSummary } from "@/lib/api";
import type { MessageContext } from "@/lib/assistant-workspace";
import { formatDate,formatNumber } from "@/lib/overview";
export function AssistantEvidenceContext({context,sources}:{context:MessageContext;sources:Array<Record<string,unknown>>}) {
  const [summary,setSummary]=useState<PortfolioSummary|null>(null),[status,setStatus]=useState<string|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{let active=true;setSummary(null);setStatus(null);setError("");if(!context.portfolio_id)return;
    void getPortfolioSummary(context.portfolio_id).then(value=>{if(active)setSummary(value)}).catch(err=>{if(active)setError(err.message)});
    void getIpsCompliance(context.portfolio_id).then(value=>{if(active)setStatus(value.status??null)}).catch(()=>{});
    return()=>{active=false};
  },[context.portfolio_id]);
  return <aside className="assistant-evidence-context" aria-label="Context and evidence"><h2>Context and evidence</h2>
    <section><h3>Next-message context</h3><p>{context.portfolio_name??"No selected portfolio"}</p><p>{context.company_name??context.symbol??"All companies"}</p></section>
    <section><h3>Stored holdings</h3><p>{summary?`${summary.holdings.length} holdings`:"—"}</p><small>{summary?formatDate(summary.data_freshness_date):""}</small></section>
    <section><h3>Market prices</h3><p>{summary?formatDate(summary.data_freshness_date):"—"}</p><small>{summary?.data_source??""}</small></section>
    <section><h3>IPS check</h3><p>{status==="PASS"?"Within mandate limits":status==="BREACH"?"Mandate issues":status==="NOT_EVALUATED"?"Not evaluated":"—"}</p>{context.portfolio_id?<Link href={`/portfolios/${context.portfolio_id}/ips` as never}>Open mandate ↗</Link>:null}</section>
    {error?<p className="assistant-warning" role="alert">{error}</p>:null}
    <section><h3>Selected answer sources</h3>{sources.length?sources.map((source,index)=><article key={index}>{typeof source.source_url==="string"&&/^https?:\/\//.test(source.source_url)?<a href={source.source_url} target="_blank" rel="noreferrer">{String(source.title??source.source_name??"Stored evidence")} ↗</a>:<p>{String(source.title??source.source_name??"Stored evidence")}</p>}{source.page_number?<small>Page {String(source.page_number)}</small>:null}{typeof source.as_of==="string"?<small>{formatDate(source.as_of)}</small>:null}</article>):<p>—</p>}</section>
    {context.symbol?<Link className="assistant-context-link" href={`/companies/${context.symbol}` as never}>Open {context.symbol} ↗</Link>:null}
    {context.portfolio_id?<Link className="assistant-context-link" href={`/portfolios/${context.portfolio_id}/quant` as never}>View analytical inputs ↗</Link>:null}
  </aside>;
}
