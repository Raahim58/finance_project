"use client";
import Link from "next/link";
import {useEffect,useRef,useState} from "react";
import {getCompanies,type Company} from "@/lib/api";
import {Icon} from "./Icon";
export function CompanyQuickSearch(){
 const [open,setOpen]=useState(false),[query,setQuery]=useState(""),[rows,setRows]=useState<Company[]>([]),[status,setStatus]=useState("idle");
 const node=useRef<HTMLDivElement>(null),input=useRef<HTMLInputElement>(null);
 useEffect(()=>{if(open)input.current?.focus();},[open]);
 useEffect(()=>{const close=(event:PointerEvent)=>{if(!node.current?.contains(event.target as Node))setOpen(false)};document.addEventListener("pointerdown",close);return()=>document.removeEventListener("pointerdown",close)},[]);
 useEffect(()=>{if(!query.trim()){setRows([]);setStatus("idle");return;}const controller=new AbortController();setStatus("loading");const timer=setTimeout(()=>void getCompanies(query.trim(),{signal:controller.signal}).then(rows=>{if(!controller.signal.aborted){setRows(rows.slice(0,8));setStatus("ready")}}).catch(()=>{if(!controller.signal.aborted)setStatus("error")}),200);return()=>{clearTimeout(timer);controller.abort()}},[query]);
 return <div className="workspace-company-search" ref={node} onKeyDown={event=>{if(event.key==="Escape")setOpen(false)}}><button className="icon-btn" aria-label="Find a company" aria-expanded={open} onClick={()=>setOpen(!open)}><Icon name="search" size={19}/></button>{open?<div className="workspace-search-popover"><input ref={input} aria-label="Find a company" placeholder="Find a company…" value={query} onChange={event=>setQuery(event.target.value)}/>{status==="loading"?<p role="status">Searching companies…</p>:status==="error"?<p role="alert">Company search unavailable.</p>:query.trim()&&!rows.length?<p>No matching companies.</p>:rows.map(row=><Link key={row.symbol} href={`/companies/${encodeURIComponent(row.symbol)}`} onClick={()=>{setOpen(false);setQuery("")}}><strong>{row.symbol}</strong><span>{row.name}</span></Link>)}</div>:null}</div>;
}
