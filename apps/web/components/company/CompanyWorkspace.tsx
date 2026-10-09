"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
import { AIBriefCard, useBrief } from "@/components/AIBriefCard";
import { getCompanyBrief } from "@/lib/api/research";
import { CompanyIntelligencePanel, CompanyPurposeEvidence } from "@/components/ResearchIntelligence";
import { Icon, type IconName } from "@/components/Icon";
import { CompanyLogo } from "@/components/markets/CompanyLogo";
import { WorkspaceHeader } from "@/components/WorkspaceHeader";
import { IndexChart } from "@/components/markets/IndexChart";
import { chartRanges,closePoints,sliceRange,type ChartRange } from "@/lib/markets";
import { TechnicalChart } from "./technical-chart/TechnicalChart";
import { formatDate, formatNumber, formatPercent, humanize, numeric } from "@/lib/overview";
import { companyFacts, factGroup, factValue, ratioDefinitions, ratioValue, type CompanyFact } from "@/lib/company";
import { useCompanyData } from "./useCompanyData";
import { DecisionWorkbench } from "./DecisionWorkbench";
import styles from "./company.module.css";

type View="overview"|"fundamentals"|"events"|"reports"|"fit";
const views:Array<[View,string,IconName]>=[["overview","Overview","document"],["fundamentals","Fundamentals","market"],["events","Events","clock"],["reports","Reports","document"],["fit","Portfolio fit","briefcase"]];
type Data=ReturnType<typeof useCompanyData>;
export function CompanyWorkspace({symbol}:{symbol:string}) {
  const data=useCompanyData(symbol), assistant=useAssistantWorkspace();
  const loadBrief=useCallback((retry:boolean)=>getCompanyBrief(symbol,retry),[symbol]);
  const briefState=useBrief(loadBrief);
  const [view,setView]=useState<View>("overview"),[range,setRange]=useState<ChartRange>("1M");
  const [statement,setStatement]=useState("ratios"),[period,setPeriod]=useState("latest"),[basis,setBasis]=useState("");
  const [metric,setMetric]=useState("cash_ratio"),[selectedFact,setSelectedFact]=useState<CompanyFact|null>(null);
  const setAssistantScope=assistant?.setCompanyPortfolioScope;
  useEffect(()=>{if(data.loaded.portfolios)setAssistantScope?.(data.portfolioId||null);},[data.loaded.portfolios,data.portfolioId,setAssistantScope]);
  const latest=data.detail?.latest_price, company=data.detail?.company;
  const shown=useMemo(()=>sliceRange(closePoints(data.history),range),[data.history,range]);
  const facts=useMemo(()=>companyFacts(data.research),[data.research]);
  const periods=Array.from(new Set(facts.map(row=>row.period_end).filter(Boolean))).sort().reverse();
  const bases=Array.from(new Set(facts.map(row=>row.accounting_basis).filter(Boolean))) as string[];
  const effectivePeriod=period==="latest"?periods[0]:period;
  const filtered=facts.filter(row=>(period==="all"||row.period_end===effectivePeriod)&&(!basis||row.accounting_basis===basis));
  const definition=ratioDefinitions.find(row=>row.key===metric)??ratioDefinitions[8];
  const derived=ratioValue(data.research,definition.key);
  const portfolioSections=data.portfolioContext?.context.sections as Record<string,{data?:{valuation_complete?:boolean}}>|undefined;
  const valuationComplete=portfolioSections?.portfolio?.data?.valuation_complete!==false;
  const scopedRatio=(key:string)=>{const result=ratioValue(data.research,key);if(!result)return undefined;
    if(period!=="all"&&effectivePeriod&&result.period_end!==effectivePeriod)return undefined;
    if(basis&&result.accounting_basis!==basis)return undefined;return result;};
  const holding=data.portfolioContext?.portfolio_relevance.find(row=>row.portfolio_id===data.portfolioId)??data.portfolioContext?.portfolio_relevance[0];
  const selectedPortfolio=data.portfolios.find(row=>row.id===data.portfolioId);
  const reportMap=new Map((data.intelligence?.reports??[]).map(row=>[row.document_id,row]));
  for(const row of data.documents.filter(doc=>["annual_report","quarterly_report","interim_report","financial_report"].includes(doc.document_type)&&doc.data_status==="observed")) {
    const stored=reportMap.get(row.id);
    reportMap.set(row.id,{document_id:row.id,title:row.title,source_url:row.source_url,source_name:row.source_name,
      document_type:row.document_type,published_date:row.published_date??undefined,pages:stored?.pages??0,chunks:stored?.chunks??0,indexed:stored?.indexed??false});
  }
  const reports=Array.from(reportMap.values()).sort((a,b)=>(b.published_date??"").localeCompare(a.published_date??""));
  const reportTable=(compact=false)=><div className={styles.tableScroll}><table className={styles.table}><thead><tr><th>Filing</th><th>Type</th><th>Published</th><th>Evidence</th></tr></thead><tbody>{(compact?reports.slice(0,3):reports).map(report=><tr key={report.document_id}><td>{report.title}</td><td>{humanize(report.document_type??"retained_report")}</td><td>{formatDate(report.published_date)}</td><td>{report.source_url?<a href={report.source_url} target="_blank" rel="noreferrer">Open report ↗</a>:<span>Source link unavailable</span>}<small>{report.indexed?`${report.pages} pages indexed`:"Narrative not indexed"}</small></td></tr>)}</tbody></table>{!reports.length?<p className={styles.empty}>{data.loaded.intelligence&&data.loaded.documents?data.errors.intelligence??"No eligible retained reports were returned.":"Loading retained reports…"}</p>:null}{!compact?<CompanyPurposeEvidence symbol={symbol}/>:null}</div>;
  return <div className={styles.workspace}>
    <WorkspaceHeader title=""><nav className="workspace-header-tabs" aria-label="Company sections">{views.map(([key,label])=><button key={key} aria-current={view===key?"page":undefined} onClick={()=>setView(key)}>{label}</button>)}</nav></WorkspaceHeader>
    <aside data-workspace-left-panel className={styles.identity} aria-label="Company navigation">
      <div className={styles.companyHeading}><CompanyLogo symbol={symbol} size={48}/><div><strong>{symbol}</strong><span>{company?.name??"Loading company…"}</span></div></div>
      <p className={styles.sector}>{company?.sector??"Sector unavailable"}</p>
      {data.errors.company?<p className={styles.error} role="alert">{data.errors.company}</p>:null}
      <div className={styles.quote}><strong>PKR {formatNumber(latest?.close)}</strong><p className={Number(latest?.change_percent)<0?styles.negative:styles.positive}>{formatPercent(latest?.change_percent)} <span>{formatDate(latest?.trade_date)}</span></p></div>
      <div className={styles.sidebarChart} aria-label={`${symbol} sidebar price history`}>{data.errors.history?<p className={styles.empty}>{data.errors.history}</p>:<IndexChart points={shown} name={symbol} height={165} compactAxis={false}/>}<div className={styles.ranges} role="group" aria-label="Company sidebar chart range">{chartRanges.map(([key])=><button key={key} aria-pressed={range===key} onClick={()=>setRange(key)}>{key}</button>)}</div><p className={styles.caption}>Stored daily closes</p></div>
      <p className={styles.caption}>{latest?.source??"Price source unavailable"}{latest?.source_url?<> · <a href={latest.source_url} target="_blank" rel="noreferrer">Source ↗</a></>:null}</p>

      <section className={styles.relevance}><h3>Portfolio relevance</h3><select aria-label="Company portfolio scope" value={data.portfolioId} onChange={e=>data.setPortfolioId(e.target.value)}><option value="">No portfolio selected</option>{data.portfolios.map(row=><option key={row.id} value={row.id}>{row.name}</option>)}</select>
        {data.portfolioId?<><div className={styles.holdingStats}><Key label="Quantity" value={formatNumber(holding?.quantity,0)}/><Key label="Market value" value={holding?.market_value==null?"—":`PKR ${formatNumber(holding.market_value,0)}`}/><Key label="Weight" value={!valuationComplete||holding?.weight==null?"—":`${formatNumber(Number(holding.weight)*100)}%`}/></div><p className={styles.caption}>{data.errors.portfolio??(!data.portfolioContext?"Loading portfolio relevance…":!valuationComplete?"Portfolio valuation is incomplete; weight is unavailable.":holding?"Stored holdings and dated market prices.":"Not held in this selected portfolio.")}</p><button className={styles.outline} onClick={()=>setView("fit")}>› Evaluate change</button></>:<p className={styles.empty}>Select a portfolio to see actual holding exposure and IPS relevance.</p>}
      </section>
      <details className={styles.coverage}><summary>Data coverage</summary>{data.coverage?Object.entries(data.coverage).filter(([,row])=>typeof row==="object"&&row!==null&&"available" in row).map(([key,row])=><p key={key}>{humanize(key)} <span>{typeof row==="object"&&row!==null&&"available" in row&&row.available?"Available":"Missing"}</span></p>):<p>{data.errors.coverage??"Loading coverage…"}</p>}</details>
    </aside>
    <div className={styles.center}>
      <div className={`${styles.content} ${view==="fit"||view==="events"?styles.tight:""}`}>
        {data.errors.research?<p className={styles.error} role="alert">Company research: {data.errors.research}</p>:null}
        {data.research?.has_synthetic_data?<p className={styles.error}>Demo company facts are labelled and do not represent observed filings.</p>:null}
        {view==="overview"?<>
          <TechnicalChart key={symbol} symbol={symbol} endDate={latest?.trade_date}/>
          <section className={styles.section}><h2>Key fundamentals</h2><div className={styles.keyFacts}>
            <Key label="Reported market cap" value={latest?.market_cap==null?"Awaiting data":`PKR ${formatNumber(latest.market_cap,1,true)}`}/>
            <Key label="P/E ratio" value={ratioValue(data.research,"pe_ratio")?factValue(ratioValue(data.research,"pe_ratio")?.value,"multiple"):(data.research?.derived_fundamentals.unavailable?.pe_ratio??"Needs eligible EPS")}/>
            <Key label="Cash ratio" value={ratioValue(data.research,"cash_ratio")?factValue(ratioValue(data.research,"cash_ratio")?.value,"multiple"):(data.research?.derived_fundamentals.unavailable?.cash_ratio??"Needs eligible inputs")}/>
            <Key label="Dividend yield" value={ratioValue(data.research,"dividend_yield")?factValue(ratioValue(data.research,"dividend_yield")?.value,"fraction"):(data.research?.derived_fundamentals.unavailable?.dividend_yield??"Calculation unavailable")}/>
            <Key label="Shares outstanding" value={formatNumber(latest?.shares_outstanding,0,true)}/><Key label="Free float" value={formatNumber(latest?.free_float_shares,0,true)}/>
          </div><button className={styles.textAction} onClick={()=>setView("fundamentals")}>View all fundamentals →</button>{latest?.capitalization_date?<p className={styles.caption}>Capitalization as of {formatDate(latest.capitalization_date)}{latest.capitalization_source_url?<> · <a href={latest.capitalization_source_url} target="_blank" rel="noreferrer">Source ↗</a></>:null}</p>:null}</section>
          <PeersSection symbol={symbol} sector={company?.sector} peers={data.peers} loaded={!!data.loaded.peers}/>
          <section className={styles.section}><div className={styles.sectionHead}><h2>Recent reports</h2><button className={styles.textAction} onClick={()=>setView("reports")}>See all reports →</button></div>{reportTable(true)}</section>
        </>:null}
        {view==="fundamentals"?<>
          <div className={styles.filters}><label>Period <select value={period} onChange={e=>{setPeriod(e.target.value);setSelectedFact(null)}}><option value="latest">Latest stored period</option><option value="all">All stored periods</option>{periods.map(value=><option key={value}>{value}</option>)}</select></label><label>Basis <select value={basis} onChange={e=>{setBasis(e.target.value);setSelectedFact(null)}}><option value="">All reported bases</option>{bases.map(value=><option key={value} value={value}>{humanize(value)}</option>)}</select></label></div>
          <nav className={styles.statementTabs} aria-label="Financial statements">{[["income","Income"],["balance","Balance sheet"],["cash","Cash flow"],["ratios","Ratios"]].map(([key,label])=><button key={key} aria-current={statement===key?"page":undefined} onClick={()=>{setStatement(key);setSelectedFact(null)}}>{label}</button>)}</nav>
          <div className={styles.tableScroll}><table className={styles.table}><thead><tr><th>Metric</th><th>Value</th><th>Reporting period</th><th>Input status / basis</th></tr></thead><tbody>
            {statement==="ratios"?ratioDefinitions.map((row,index)=>{const result=scopedRatio(row.key);return <Rows key={row.key} group={index===0||row.group!==ratioDefinitions[index-1].group?row.group:undefined}><tr aria-selected={!selectedFact&&metric===row.key}><td><button onClick={()=>{setMetric(row.key);setSelectedFact(null)}}>{row.label}</button></td><td>{result&&numeric(result.value)!=null?factValue(result.value,row.unit):"Needs eligible inputs"}</td><td>{result?.period_end?String(result.period_end):"—"}</td><td>{result?String(result.warning??"Calculated from stored facts"):data.research?.derived_fundamentals.unavailable?.[row.key]??"Not calculated"}</td></tr></Rows>}):filtered.filter(row=>factGroup(row.taxonomy_key)===statement).map((row,index)=><tr key={row.id??`${row.taxonomy_key}-${index}`} aria-selected={selectedFact?.id===row.id&&!!selectedFact}><td><button onClick={()=>setSelectedFact(row)}>{humanize(row.taxonomy_key)}</button></td><td>{factValue(row.value,row.unit,row.currency)}</td><td>{row.period_start?`${formatDate(row.period_start)} – `:""}{formatDate(row.period_end)}<small>{humanize(row.period_type)}</small></td><td>{humanize(row.accounting_basis??"basis_unavailable")}<small>Extracted · source review</small></td></tr>)}
          </tbody></table></div>
          {statement!=="ratios"&&!filtered.some(row=>factGroup(row.taxonomy_key)===statement)?<p className={styles.empty}>{data.loaded.research?"No stored eligible facts for this statement, period and basis.":"Loading structured facts…"}</p>:null}
          <p className={styles.caption}>{facts.length} returned facts · all matching rows are displayed. Extracted amounts retain their reported units; source review is distinct from calculation eligibility.</p>
          <section className={styles.section}><h2>Source reconciliation</h2>{reportTable(true)}</section>
        </>:null}
        {view==="events"?<><CompanyIntelligencePanel symbol={symbol} portfolioId={data.portfolioId||undefined}/></>:null}
        {view==="reports"?<>{reportTable()}</>:null}
        {view==="fit"?<><p className={styles.description}>Evaluate this company against an explicitly selected portfolio and its confirmed IPS.</p><DecisionWorkbench symbol={symbol} instrumentId={data.research?.instrument.id} portfolios={data.portfolios} selectedPortfolioId={data.portfolioId}/></>:null}
      </div>
    </div>
    <aside className={styles.right} aria-label="Company context">
      <div className={styles.rightBody}>{view==="fundamentals"?<section className={styles.metricInspector}>
        <h2>{selectedFact?"Stored financial observation":"How this metric is built"}</h2><p className={styles.caption}>Metric</p><h3>{selectedFact?humanize(selectedFact.taxonomy_key):definition.label}</h3>
        <p className={styles.caption}>{selectedFact?"Value":"Formula"}</p><p>{selectedFact?factValue(selectedFact.value,selectedFact.unit,selectedFact.currency):definition.formula}</p>
        {selectedFact?<><p className={styles.caption}>Period and accounting basis</p><p>{formatDate(selectedFact.period_end)} · {humanize(selectedFact.accounting_basis??"unknown")}</p><p className={styles.caption}>Source label</p><p>{selectedFact.source_label??selectedFact.provenance.source_name??"Source unavailable"}</p>{selectedFact.source_url?<a href={selectedFact.source_url} target="_blank" rel="noreferrer">Open source ↗</a>:<p className={styles.caption}>Source URL unavailable; use retained report evidence.</p>}</>:<><div className={styles.inputList}><h3>Required inputs</h3>{definition.inputs.map(key=>{const fact=filtered.find(row=>row.taxonomy_key===key);return <div key={key}><span>{humanize(key)}</span><span>{key==="price"&&latest?`PKR ${formatNumber(latest.close)}`:fact?"Stored · source review":"Missing eligible input"}</span></div>})}</div><div className={styles.inputList}><p>Period consistent? <span>{derived?.period_end?"Backend evaluated":"Not established"}</span></p><p>Calculation <span>{derived?"Returned by backend":"Unavailable"}</span></p></div></>}
      </section>:null}
      <section className={styles.brief}><h2 className={styles.briefTitle}>Company brief</h2><AIBriefCard title="Company brief" hideHeader state={briefState} onAsk={text=>assistant?.open(text)}/></section></div>
    </aside>
  </div>;
}
function Key({label,value}:{label:string;value:string}){return <div><span>{label}</span><strong>{value}</strong></div>}
function Rows({children,group}:{children:React.ReactNode;group?:string}){return <>{group?<tr className={styles.group}><td colSpan={4}>{group}</td></tr>:null}{children}</>}

function PeersSection({symbol,sector,peers,loaded}:{symbol:string;sector?:string;peers:Array<{symbol:string;name:string;close?:string;change_percent?:string;market_cap?:string|null}>;loaded:boolean}){
  return <section className={styles.section}><h2>Peers{sector?` · ${sector}`:""}</h2>{peers.length?<div className={styles.tableScroll}><table className={styles.table}><thead><tr><th>Company</th><th>Price</th><th>Change</th><th>Market cap</th></tr></thead><tbody>{peers.map(row=><tr key={row.symbol}><td><Link href={`/companies/${encodeURIComponent(row.symbol)}` as never}><CompanyLogo symbol={row.symbol} size={20}/> {row.symbol}</Link><small>{row.name}</small></td><td>{row.close?formatNumber(row.close):"—"}</td><td className={Number(row.change_percent)<0?styles.negative:styles.positive}>{row.change_percent==null?"—":formatPercent(row.change_percent)}</td><td>{row.market_cap?formatNumber(row.market_cap,1,true):"—"}</td></tr>)}</tbody></table></div>:<p className={styles.empty}>{loaded?`No other listed companies in ${sector??"this sector"} were returned for ${symbol}.`:"Loading peers…"}</p>}</section>;
}
