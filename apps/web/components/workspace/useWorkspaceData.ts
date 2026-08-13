"use client";

import { useEffect, useRef, useState } from "react";
import {
  AllocationSet, AuditEvent, CapitalMarketAssumptions, CapmSml, EfficientFrontier, IpsVersion,
  PortfolioExposure, PortfolioPerformancePoint, PortfolioQuant, PortfolioRiskFlag, PortfolioSummary,
  ReturnDistribution, RiskBudget, RollingRisk, ScenarioResult, Transaction,
  getAllocations, getAuditEvents, getCapitalMarketAssumptions, getCapmSml, getEfficientFrontier,
  getIpsCompliance, getIpsVersions, getPortfolioExposure, getPortfolioPerformance, getPortfolioQuant,
  getPortfolioSummary, getReturnDistribution, getRiskBudget, getRollingRisk, getScenarioRuns, getTransactions,
} from "@/lib/api";

export type WorkspaceCompliance={compliant:boolean;status?:"PASS"|"BREACH"|"NOT_EVALUATED";checks?:Array<Record<string,unknown>>;violations:Array<Record<string,unknown>>;not_evaluated?:Array<Record<string,unknown>>;ips_version_id?:string|null};
export type WorkspaceData={
  summary:PortfolioSummary|null; exposure:PortfolioExposure|null; performance:PortfolioPerformancePoint[];
  quant:PortfolioQuant|null; flags:PortfolioRiskFlag[]; allocations:AllocationSet[]; transactions:Transaction[];
  scenarios:ScenarioResult[]; compliance:WorkspaceCompliance|null; ips:IpsVersion[]; assumptions:CapitalMarketAssumptions|null;
  frontier:EfficientFrontier|null; capm:CapmSml|null; rolling:RollingRisk|null; distribution:ReturnDistribution|null;
  riskBudget:RiskBudget|null; auditEvents:AuditEvent[];
};

const blank:WorkspaceData={summary:null,exposure:null,performance:[],quant:null,flags:[],allocations:[],transactions:[],scenarios:[],compliance:null,ips:[],assumptions:null,frontier:null,capm:null,rolling:null,distribution:null,riskBudget:null,auditEvents:[]};

export function useWorkspaceData(portfolioId:string, mode:string){
  const [data,setData]=useState<WorkspaceData>(blank);const [loading,setLoading]=useState(true);const [message,setMessage]=useState("");const [failures,setFailures]=useState<string[]>([]);const [analyticsLoading,setAnalyticsLoading]=useState(false);
  const dataRef=useRef(data);dataRef.current=data;
  const previousPortfolioIdRef=useRef<string|null>(null);
  useEffect(()=>{
    const portfolioChanged=previousPortfolioIdRef.current!==portfolioId;previousPortfolioIdRef.current=portfolioId;
    let active=true;
    if(portfolioChanged){setData(blank);dataRef.current=blank}
    setAnalyticsLoading(false);setMessage("");setFailures([]);
    const update=(values:Partial<WorkspaceData>)=>active&&setData(current=>({...current,...values}));
    const fail=(slice:string)=>(error:unknown)=>{if(active)setFailures(current=>[...current,`${slice}: ${error instanceof Error?error.message:"request failed"}`])};
    const tasks:Promise<unknown>[]=[];
    const needsSummary=["overview","build","risk","stress","scenarios"].includes(mode);
    const summaryAlreadyLoaded=!portfolioChanged&&Boolean(dataRef.current.summary);
    if(needsSummary){setLoading(!summaryAlreadyLoaded);tasks.push(getPortfolioSummary(portfolioId).then(summary=>update({summary})).catch((error:Error)=>active&&setMessage(error.message)).finally(()=>active&&setLoading(false)))}else setLoading(false);
    if(mode==="overview")tasks.push(getPortfolioExposure(portfolioId).then(exposure=>update({exposure})).catch(fail("Exposure request failed")),getPortfolioPerformance(portfolioId).then(performance=>update({performance})).catch(fail("Performance request failed")),getIpsCompliance(portfolioId).then(compliance=>update({compliance})).catch(fail("Compliance request failed")),getIpsVersions(portfolioId).then(ips=>update({ips})).catch(fail("IPS request failed")));
    if(mode==="build")tasks.push(getIpsVersions(portfolioId).then(ips=>update({ips})).catch(fail("IPS request failed")),getAllocations(portfolioId).then(allocations=>update({allocations})).catch(fail("Allocation request failed")),getCapitalMarketAssumptions(portfolioId).then(assumptions=>update({assumptions})).catch(fail("Assumptions request failed")),getRiskBudget(portfolioId).then(riskBudget=>update({riskBudget})).catch(fail("Risk budget request failed")));
    if(["overview","quant","risk"].includes(mode)){setAnalyticsLoading(true);tasks.push(getPortfolioQuant(portfolioId).then(quant=>update({quant})).catch(fail("Analytics request failed")).finally(()=>active&&setAnalyticsLoading(false)))}
    if(mode==="quant")tasks.push(getRiskBudget(portfolioId).then(riskBudget=>update({riskBudget})).catch(fail("Risk budget request failed")));
    if(mode==="risk")tasks.push(getPortfolioExposure(portfolioId).then(exposure=>update({exposure})).catch(fail("Exposure request failed")),getIpsCompliance(portfolioId).then(compliance=>update({compliance})).catch(fail("Compliance request failed")),getRiskBudget(portfolioId).then(riskBudget=>update({riskBudget})).catch(fail("Risk budget request failed")));
    if(mode==="activity")tasks.push(getTransactions(portfolioId).then(transactions=>update({transactions})).catch(fail("Transaction request failed")),getAuditEvents(portfolioId).then(auditEvents=>update({auditEvents})).catch(fail("Audit trail request failed")));
    if(mode==="stress"||mode==="scenarios")tasks.push(getScenarioRuns(portfolioId).then(scenarios=>update({scenarios})).catch(fail("Scenario history request failed")));
    if(mode==="settings"||mode==="ips")tasks.push(getIpsCompliance(portfolioId).then(compliance=>update({compliance})).catch(fail("Compliance request failed")),getIpsVersions(portfolioId).then(ips=>update({ips})).catch(fail("IPS request failed")));
    void Promise.all(tasks).catch((error:Error)=>active&&setMessage(error.message));
    return()=>{active=false};
  },[portfolioId,mode]);
  return {data,loading,message,setMessage,failures,analyticsLoading};
}
