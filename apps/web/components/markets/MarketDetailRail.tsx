"use client";
import Link from "next/link";
import {useEffect,useMemo,useState} from "react";
import {getCompanyHistory,getDocuments,getPortfolios,getPortfolioSummary,type Company,type MarketPrice,type MarketOverview,type PortfolioSummary,type ApiDocument} from "@/lib/api";
import {useAssistantWorkspace} from "@/components/AssistantWorkspace";
import {Icon} from "@/components/Icon";
import {closePoints} from "@/lib/markets";
import {formatDate,formatNumber,formatPercent,numeric} from "@/lib/overview";
import {CompanyLogo} from "./CompanyLogo";
import {IndexChart} from "./IndexChart";
import styles from "./markets.module.css";
export type MarketSelection={kind:"company";symbol:string}|{kind:"sector";sector:string};
export function MarketDetailRail({selection,companies,market,onClose,onCompany,onSector}:{onSector?:(sector:string)=>void;selection:MarketSelection;companies:Company[];market:MarketOverview|null;onClose:()=>void;onCompany:(symbol:string)=>void}){
 const assistant=useAssistantWorkspace();
 const [summary,setSummary]=useState<PortfolioSummary|null>(null),[portfolioState,setPortfolioState]=useState("loading"),[query,setQuery]=useState("");
 const [history,setHistory]=useState<MarketPrice[]>([]),[reports,setReports]=useState<ApiDocument[]>([]),[historyState,setHistoryState]=useState("loading");
 const symbol=selection.kind==="company"?selection.symbol:null;
 useEffect(()=>{
  let active=true,sequence=0;
  const load=async()=>{const request=++sequence;setSummary(null);setPortfolioState("loading");
   try{const portfolios=await getPortfolios();if(!active||request!==sequence)return;
    const portfolio=portfolios.find(row=>row.is_default&&!row.archived_at);
    if(!portfolio){setPortfolioState("none");return;}
    const value=await getPortfolioSummary(portfolio.id);
    if(active&&request===sequence){setSummary(value);setPortfolioState("ready");}
   }catch{if(active&&request===sequence)setPortfolioState("error");}
  };
  void load();window.addEventListener("psx-portfolio-change",load);
  return()=>{active=false;window.removeEventListener("psx-portfolio-change",load);};
 },[]);
 useEffect(()=>{setQuery("")},[selection.kind,selection.kind==="sector"?selection.sector:selection.symbol]);
 useEffect(()=>{let active=true;setHistory([]);setReports([]);setHistoryState("loading");if(!symbol)return;void getCompanyHistory(symbol,120).then(rows=>{if(active){setHistory(rows);setHistoryState("ready")}}).catch(()=>{if(active)setHistoryState("error")});void getDocuments(symbol).then(rows=>{if(active)setReports(rows.filter(row=>["annual_report","quarterly_report","interim_report","financial_report"].includes(row.document_type)&&row.data_status==="observed").sort((a,b)=>(b.published_date??b.created_at).localeCompare(a.published_date??a.created_at)))}).catch(()=>{});return()=>{active=false}},[symbol]);
 const prices=useMemo(()=>new Map((market?.prices??[...(market?.top_gainers??[]),...(market?.top_losers??[]),...(market?.top_volume??[])]).map(row=>[row.symbol,row])),[market]);
 const company=companies.find(row=>row.symbol===symbol),points=useMemo(()=>closePoints(history),[history]);
 const price=symbol?prices.get(symbol)??history.slice().sort((a,b)=>b.trade_date.localeCompare(a.trade_date))[0]:undefined;
 const holding=symbol?summary?.holdings.find(row=>row.symbol===symbol):undefined;
 const weight=(issuer:string)=>{const row=summary?.holdings.find(row=>row.symbol===issuer);if(!summary?.valuation_complete||numeric(summary.total_value)==null||Number(summary.total_value)<=0||!row||numeric(row.market_value)==null)return null;return Number(row.market_value)/Number(summary.total_value)*100;};
 const portfolioNote=portfolioState==="loading"?"Loading portfolio exposure…":portfolioState==="error"?"Portfolio exposure unavailable.":portfolioState==="none"?"Select a portfolio to see holding weights.":!summary?.valuation_complete?"Portfolio valuation is incomplete; weights are unavailable.":`Source: Stored holdings and prices · ${formatDate(summary.data_freshness_date)} · ${summary.portfolio.name}`;
 const sector=selection.kind==="sector"?selection.sector:company?.sector;
 const matches=companies.filter(row=>row.sector===sector&&`${row.symbol} ${row.name}`.toLowerCase().includes(query.trim().toLowerCase())).sort((a,b)=>(prices.get(b.symbol)?.volume??-1)-(prices.get(a.symbol)?.volume??-1)||a.symbol.localeCompare(b.symbol));
 const held=new Set(summary?.holdings.map(row=>row.symbol)??[]),shown=query.trim()?matches:matches.slice(0,8),otherHeld=query.trim()?[]:matches.filter(row=>held.has(row.symbol)&&!shown.some(value=>value.symbol===row.symbol));
 const ask=(question:string)=>assistant?.open(question);
 return <aside className={`${styles.rail} ${styles.detailRail}`} aria-label={symbol?`${symbol} market detail`:`${sector} sector detail`}>
  <div className={styles.detailHead}>{symbol?<div className={styles.detailIdentity}><CompanyLogo symbol={symbol} website={company?.official_website} size={40}/><div><h2>{symbol}</h2><p>{company?.name??"Company name unavailable"}</p></div></div>:<div><h2>{sector}</h2><p>Sector overview</p></div>}<button className="icon-btn" aria-label="Close market detail" onClick={onClose}><Icon name="close" size={18}/></button></div>
  {symbol?<><div className={styles.detailQuote}><div><strong>{formatNumber(price?.close)}</strong><span className={Number(price?.change_percent)<0?styles.negative:styles.positive}>{formatPercent(price?.change_percent)}</span></div><div><small>My holding</small><b>{weight(symbol)!=null?`${weight(symbol)!.toFixed(2)}%`:holding?"Unavailable":portfolioState==="ready"?"Not held":"—"}</b></div></div>
  {historyState==="loading"?<p className={styles.source}>Loading stored price history…</p>:historyState==="error"?<p className={styles.source}>Stored price history unavailable.</p>:<IndexChart points={points} name={symbol} height={165} compactAxis={false}/>}
  <p className={styles.source}>Stored daily closes · no intraday reconstruction</p>
  <dl className={styles.detailFacts}><div><dt>Date</dt><dd>{formatDate(price?.trade_date)}</dd></div><div><dt>Related report</dt><dd>{reports[0]?<a href={reports[0].source_url??`/companies/${symbol}`}>{formatDate(reports[0].published_date)} ↗</a>:"Unavailable"}</dd></div><div><dt>Sector</dt><dd>{sector&&onSector?<button onClick={()=>onSector(sector)}>{sector} ›</button>:sector??"Unavailable"}</dd></div></dl>
  <p className={styles.source}>{price?.source??"Price source unavailable"}{price?.source_url?<> · <a href={price.source_url} target="_blank" rel="noreferrer">Source ↗</a></>:null}</p>
  <section className={styles.detailDeeper}><h3>Go deeper</h3><Link href={`/companies/${encodeURIComponent(symbol)}`}><Icon name="expand" size={16}/>Open company <span>›</span></Link><button onClick={()=>ask(`Explain ${symbol} using its dated company and market evidence; state missing data.`)}><Icon name="assistant" size={16}/>Ask about {symbol}<span>›</span></button></section></>:<>
   <label className={styles.sectorSearch}><Icon name="search" size={16}/><input aria-label={`Search companies in ${sector}`} placeholder="Search this sector…" value={query} onChange={event=>setQuery(event.target.value)}/></label>
   <p className={styles.source}>{query.trim()?`${matches.length} matching companies`:"Top companies by observed traded volume"}</p>
   <div className={styles.sectorCompanies}>{[...shown,...otherHeld].map(row=><div key={row.symbol}><button onClick={()=>onCompany(row.symbol)}><CompanyLogo symbol={row.symbol} website={row.official_website} size={25}/><b>{row.symbol}</b><span>{formatNumber(prices.get(row.symbol)?.close)}</span><span className={Number(prices.get(row.symbol)?.change_percent)<0?styles.negative:styles.positive}>{formatPercent(prices.get(row.symbol)?.change_percent)}</span></button>{held.has(row.symbol)?<p><span>Held in portfolio</span><b>{weight(row.symbol)==null?"Unavailable":`${weight(row.symbol)!.toFixed(2)}%`}</b></p>:null}</div>)}</div>
   {!matches.length?<p className={styles.source}>No companies match this sector search.</p>:null}
   <section className={styles.detailDeeper}><h3>Go deeper</h3><button onClick={()=>ask(`How does my stored ${sector} sector exposure compare? Use my selected portfolio and dated database evidence.`)}>↳ How does my exposure compare?</button><button onClick={()=>ask(`Show cited company and sector evidence for ${sector}.`)}>↳ Show sector evidence</button></section>
  </>}
  <p className={styles.source}>{portfolioNote}</p><RailComposer ask={ask}/>
 </aside>;
}
function RailComposer({ask}:{ask:(text:string)=>void}){const [question,setQuestion]=useState("");return <form className={styles.detailComposer} onSubmit={event=>{event.preventDefault();if(question.trim())ask(question.trim())}}><textarea aria-label="Ask about market detail" placeholder="Ask anything…" value={question} onChange={event=>setQuestion(event.target.value)}/><button disabled={!question.trim()} aria-label="Open market question in Assistant">↑</button><small>Verify cited evidence and dated observations.</small></form>}
