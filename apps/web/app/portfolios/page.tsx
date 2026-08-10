"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { Portfolio, createPortfolio, getPortfolios } from "@/lib/api";

export default function PortfoliosPage() {
  const [rows, setRows] = useState<Portfolio[]>([]); const [message, setMessage] = useState("");
  useEffect(() => { void getPortfolios().then(setRows).catch((error: Error) => setMessage(error.message)); }, []);
  async function create(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const name = String(new FormData(event.currentTarget).get("name")); const row = await createPortfolio(name); setRows([...rows, row]); }
  return <section className="mx-auto grid max-w-6xl gap-6 px-5 py-8"><div><h1 className="text-2xl font-semibold">Portfolios</h1><p className="mt-2 text-sm text-muted">Independent, user-owned workspaces with auditable ledgers and IPS versions.</p></div>{message ? <p>{message}</p> : null}<form onSubmit={create} className="flex gap-3 rounded-lg border border-line bg-white p-4"><input name="name" placeholder="Portfolio name" className="flex-1 rounded-md border border-line px-3 py-2" required /><button className="rounded-md bg-accent px-4 py-2 text-white">Create</button></form><div className="grid gap-4 md:grid-cols-2">{rows.map((row) => <Link key={row.id} href={`/portfolios/${row.id}/overview`} className="rounded-lg border border-line bg-white p-5"><div className="flex justify-between"><h2 className="font-semibold">{row.name}</h2>{row.is_default ? <span className="text-xs text-accent">Default</span> : null}</div><p className="mt-2 text-sm text-muted">{row.goal_summary || "No goal summary yet"}</p><p className="mt-3 text-xs text-muted">{row.history_complete ? "Complete ledger history" : "History begins at opening-balance baseline"}</p></Link>)}</div></section>;
}
