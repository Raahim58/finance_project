"use client";

import { useParams } from "next/navigation";
import { Icon } from "@/components/Icon";
import { OverviewTab } from "@/components/portfolio/OverviewTab";
import { BuildTab } from "@/components/portfolio/BuildTab";
import { RiskTab } from "@/components/portfolio/RiskTab";
import { QuantTab } from "@/components/portfolio/QuantTab";
import { ScenariosTab } from "@/components/portfolio/ScenariosTab";
import { WorkspaceDataNotices } from "./WorkspaceDataNotices";
import { PortfolioWorkspace } from "@/components/PortfolioWorkspace";
import { useWorkspaceData, type WorkspaceData } from "@/components/workspace/useWorkspaceData";

export function WorkspacePage({mode}:{mode:string}){
  const {portfolioId}=useParams<{portfolioId:string}>();
  const {data,loading,message,setMessage,failures,analyticsLoading}=useWorkspaceData(portfolioId,mode);
  const activeMode=mode==="scenarios"?"stress":mode==="ips"?"settings":mode;
  return <PortfolioWorkspace portfolioId={portfolioId} active={activeMode}><WorkspaceDataNotices ready={!loading} scope={`${portfolioId}:${mode}`}>{message?<div className="notice notice-warn mb-3"><Icon name="warning"/><span>{message}</span></div>:null}{failures.length?<div className="notice notice-error mb-3" role="alert"><Icon name="warning"/><span><strong>Some data requests failed.</strong> {failures.join(" · ")} Empty sections below must not be interpreted as confirmed absence.</span></div>:null}</WorkspaceDataNotices>{loading?<Loading/>:<Mode mode={mode} portfolioId={portfolioId} data={data} setMessage={setMessage} analyticsLoading={analyticsLoading}/>}</PortfolioWorkspace>;
}

function Loading(){return <div className="grid gap-3"><div className="metric-strip grid-cols-4">{[1,2,3,4].map(i=><div className="metric" key={i}><div className="skeleton h-3 w-20"/><div className="skeleton mt-3 h-7 w-28"/></div>)}</div><div className="panel h-80 p-4"><div className="skeleton h-full w-full"/></div></div>}
function Mode({mode,analyticsLoading,...props}:{mode:string;portfolioId:string;data:WorkspaceData;setMessage:(s:string)=>void;analyticsLoading:boolean}){
  if(mode==="overview")return <OverviewTab {...props}/>;
  if(mode==="build")return <BuildTab {...props}/>;
  if(mode==="quant")return <QuantTab {...props} loading={analyticsLoading}/>;
  if(mode==="risk")return <RiskTab {...props}/>;
  if(mode==="scenarios")return <ScenariosTab {...props}/>;
  return null;
}
