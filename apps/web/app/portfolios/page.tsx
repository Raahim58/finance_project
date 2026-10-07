"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { getPortfolios } from "@/lib/api";

// "Portfolios" opens the globally selected (server-side default) portfolio.
export default function PortfoliosEntry() {
  const router = useRouter();
  const [state, setState] = useState<"loading" | "empty" | "error">("loading");
  useEffect(() => {
    let active = true;
    getPortfolios().then(rows => {
      const open = rows.filter(row => !row.archived_at);
      const target = open.find(row => row.is_default) ?? open[0];
      if (!active) return;
      if (target) router.replace(`/portfolios/${target.id}/overview` as never);
      else setState("empty");
    }).catch(() => { if (active) setState("error"); });
    return () => { active = false; };
  }, [router]);
  if (state === "loading") return <div className="page-wrap"><div className="panel h-96 skeleton" /></div>;
  return <div className="page-wrap"><div className="empty-state"><strong>{state === "empty" ? "No portfolios yet" : "Portfolios could not be loaded"}</strong>
    <span>{state === "empty" ? "Create a portfolio to start building and analysing." : "Try refreshing the page."}</span>
    {state === "empty" ? <Link className="btn btn-primary mt-3" href={"/portfolios/manage" as never}>Create a portfolio</Link> : null}</div></div>;
}
