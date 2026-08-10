"use client";

import { FormEvent, useState } from "react";
import { RagSearchResponse, searchRag } from "@/lib/api";

export default function ResearchPage() {
  const [result, setResult] = useState<RagSearchResponse | null>(null);
  async function submit(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setResult(await searchRag({ query: String(new FormData(event.currentTarget).get("query")), limit: 10 })); }
  return <section className="mx-auto grid max-w-6xl gap-5 px-5 py-8"><div><h1 className="text-2xl font-semibold">Research</h1><p className="mt-2 text-sm text-muted">Search public and user-owned document text. Exact market and financial values remain structured database queries.</p></div><form onSubmit={submit} className="flex gap-3 rounded-lg border border-line bg-white p-5"><input name="query" className="flex-1 rounded-md border border-line px-3 py-2" placeholder="Search reports and announcements" required /><button className="rounded-md bg-accent px-4 py-2 text-white">Search</button></form><div className="grid gap-3">{result?.chunks.map((chunk) => <article key={chunk.id} className="rounded-lg border border-line bg-white p-5"><div className="flex justify-between text-xs text-muted"><span>{chunk.citation.title}</span><span>Page {chunk.page_number ?? "n/a"} · score {chunk.score}</span></div><p className="mt-3 text-sm leading-6">{chunk.chunk_text}</p>{chunk.citation.source_url ? <a className="mt-3 block text-sm text-accent" href={chunk.citation.source_url}>Open source</a> : null}</article>)}</div></section>;
}
