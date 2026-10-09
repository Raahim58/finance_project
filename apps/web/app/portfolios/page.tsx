"use client";
import Link from "next/link";
import {useEffect,useState} from "react";
import {useRouter} from "next/navigation";
import {getPortfolios} from "@/lib/api";
export default function PortfoliosEntry(){
 const router=useRouter();const [state,setState]=useState<"loading"|"missing"|"error">("loading");
 useEffect(()=>{let active=true;void getPortfolios().then(rows=>{if(!active)return;const selected=rows.find(row=>row.is_default&&!row.archived_at);if(selected)router.replace(`/portfolios/${selected.id}/overview` as never);else setState("missing")}).catch(()=>{if(active)setState("error")});return()=>{active=false}},[router]);
 if(state==="loading")return <p className="p-6 text-sm text-muted" role="status">Opening selected portfolio…</p>;
 return <div className="page-wrap"><p>{state==="error"?"The selected portfolio could not be loaded.":"No global portfolio is selected."}</p><Link className="btn btn-secondary mt-4" href="/portfolios/manage">Select or create a portfolio</Link></div>;
}
