"use client";
import type {ApiDocument} from "@/lib/api";
import {date,human,styles} from "./Common";
export function DocumentEvidenceReader({document,page,pageNumber,setPageNumber,loading,readPage,back}:{document:ApiDocument;page:{title:string;page_number:number;text:string}|null;pageNumber:string;setPageNumber:(value:string)=>void;loading:boolean;readPage:()=>Promise<void>;back:()=>void}){
 const original=document.source_url&&/^https?:\/\//.test(document.source_url)?document.source_url:null;
 return <article className={styles.reader} aria-label="Document evidence reader">
  <div className={styles.readerNav}><button onClick={back}>← All documents</button><span>{human(document.document_type)}</span></div>
  <p className={styles.readerSource}>{document.source_name} · Published {date(document.published_date)}</p>
  <div className={styles.readerControls}><label>Page <input aria-label="Stored document page" type="number" min="1" value={pageNumber} onChange={event=>setPageNumber(event.target.value)}/></label><button disabled={loading||!Number.isInteger(Number(pageNumber))||Number(pageNumber)<1} onClick={()=>void readPage()}>{loading?"Loading…":"Read stored page"}</button>{original?<a href={original} target="_blank" rel="noreferrer">Open original report ↗</a>:<span>Original URL unavailable</span>}</div>
  {page?<><p className={styles.source}>Original stored text · Page {page.page_number}</p><div className={styles.documentPage}>{page.text}</div></>:<div className={styles.documentPlaceholder}><h3>Original evidence</h3><p>Read a retained page here, or open the original source. Document text is kept separate from verified numerical facts.</p>{original?<a href={original} target="_blank" rel="noreferrer">View original report ↗</a>:null}</div>}
  <section className={styles.section}><h3>Source record</h3><dl className={styles.detail}><dt>Published</dt><dd>{date(document.published_date)}</dd><dt>Reporting year</dt><dd>{document.fiscal_year??"—"}</dd><dt>Quarter</dt><dd>{document.quarter??"—"}</dd><dt>Document status</dt><dd>{human(document.status)}</dd><dt>Accounting basis</dt><dd>—</dd><dt>Verified exact amounts</dt><dd>—</dd></dl></section>
 </article>;
}
