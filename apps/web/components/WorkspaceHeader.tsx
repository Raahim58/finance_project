"use client";
import { useEffect, useState, type ReactNode } from "react";
import {PortfolioTabs} from "./PortfolioTabs";
import { createPortal } from "react-dom";

/** Render screen controls in the shared shell header; keep a local fallback for isolated views. */
export function WorkspaceHeader({title,children}:{title:string;children?:ReactNode}) {
  const [target,setTarget]=useState<HTMLElement|null>(null);
  useEffect(()=>{setTarget(document.getElementById("workspace-header-content"));},[]);
  const content=<div className="workspace-page-header">{title?<h1>{title}</h1>:null}{target?.dataset.portfolioId?<PortfolioTabs/>:null}{children}</div>;
  return target?createPortal(content,target):content;
}
