import { Suspense } from "react";
import { WorkspacePage } from "@/components/WorkspacePage";

export default function Page() {
  return <Suspense fallback={<div className="page-wrap"><div className="panel h-96 skeleton" /></div>}><WorkspacePage mode="build" /></Suspense>;
}
