"use client";
import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
function Prefill(){const params=useSearchParams(),open=useAssistantWorkspace()?.open;const question=params.get("question");useEffect(()=>{if(question)open?.(question)},[open,question]);return <h1 className="sr-only">Assistant workspace</h1>}
export default function AssistantPage(){return <Suspense><Prefill/></Suspense>}
