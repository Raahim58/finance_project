"use client";
import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAssistantWorkspace } from "@/components/AssistantWorkspace";
function AssistantRedirect() {
  const router = useRouter(),
    params = useSearchParams(),
    workspace = useAssistantWorkspace();
  useEffect(() => {
    workspace?.open(params.get("question") ?? undefined);
    router.replace("/dashboard");
  }, [router, params, workspace]);
  return <p className="p-6 text-sm text-muted">Opening Assistant…</p>;
}
export default function AssistantPage() {
  return (
    <Suspense>
      <AssistantRedirect />
    </Suspense>
  );
}
