"use client";

import { FormEvent, useEffect, useState } from "react";

import { ApiDocument, RagSearchResponse, getDocuments, searchRag, uploadDocument } from "@/lib/api";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<ApiDocument[]>([]);
  const [searchResults, setSearchResults] = useState<RagSearchResponse | null>(null);
  const [title, setTitle] = useState("Demo annual report snippet");
  const [documentType, setDocumentType] = useState("annual_report");
  const [symbol, setSymbol] = useState("MEBL");
  const [sourceName, setSourceName] = useState("manual");
  const [query, setQuery] = useState("deposit growth");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadDocuments() {
    const rows = await getDocuments();
    setDocuments(rows);
  }

  useEffect(() => {
    void loadDocuments()
      .catch((error: Error) => setMessage(error.message))
      .finally(() => setLoading(false));
  }, []);

  async function onUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setMessage("Select a text, Markdown, or PDF file first.");
      return;
    }
    const formData = new FormData();
    formData.set("file", file);
    formData.set("title", title);
    formData.set("document_type", documentType);
    formData.set("symbol", symbol.toUpperCase());
    formData.set("source_name", sourceName);
    try {
      const created = await uploadDocument(formData);
      setDocuments([created, ...documents]);
      setMessage("Document uploaded, parsed, chunked, embedded, and cited.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Upload failed");
    }
  }

  async function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const result = await searchRag({
        query,
        symbols: symbol ? [symbol.toUpperCase()] : undefined,
        document_types: documentType ? [documentType] : undefined,
        limit: 5
      });
      setSearchResults(result);
      setMessage(result.chunks.length ? null : "No matching cited context found.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Search failed");
    }
  }

  if (loading) {
    return <section className="page-wrap text-sm text-muted">Loading documents...</section>;
  }

  return (
    <section className="page-wrap grid gap-4">
      <header className="page-heading">
        <div><p className="eyebrow">Evidence operations</p><h1 className="page-title">Document library</h1>
        <p className="page-subtitle">
          Upload documents, preserve metadata, and search cited chunks. RAG is for unstructured text only.
        </p></div>
      </header>

      {message ? <p className="notice">{message}</p> : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <form onSubmit={onUpload} className="panel grid gap-4 p-5">
          <h2 className="text-base font-semibold text-ink">Upload document</h2>
          <label className="grid gap-2 text-sm text-ink">
            File
            <input
              className="field"
              type="file"
              accept=".txt,.md,.pdf,text/plain,application/pdf"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
          </label>
          <label className="grid gap-2 text-sm text-ink">
            Title
            <input className="field" value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="grid gap-2 text-sm text-ink">
              Type
              <input className="field" value={documentType} onChange={(event) => setDocumentType(event.target.value)} />
            </label>
            <label className="grid gap-2 text-sm text-ink">
              Symbol
              <input className="field uppercase" value={symbol} onChange={(event) => setSymbol(event.target.value)} />
            </label>
            <label className="grid gap-2 text-sm text-ink">
              Source
              <input className="field" value={sourceName} onChange={(event) => setSourceName(event.target.value)} />
            </label>
          </div>
          <button className="btn btn-primary" type="submit">
            Upload
          </button>
        </form>

        <form onSubmit={onSearch} className="panel grid content-start gap-4 p-5">
          <h2 className="text-base font-semibold text-ink">Search cited context</h2>
          <label className="grid gap-2 text-sm text-ink">
            Query
            <input className="field" value={query} onChange={(event) => setQuery(event.target.value)} />
          </label>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="grid gap-2 text-sm text-ink">
              Symbol filter
              <input className="field uppercase" value={symbol} onChange={(event) => setSymbol(event.target.value)} />
            </label>
            <label className="grid gap-2 text-sm text-ink">
              Type filter
              <input className="field" value={documentType} onChange={(event) => setDocumentType(event.target.value)} />
            </label>
          </div>
          <button className="btn btn-primary" type="submit">
            Search
          </button>
        </form>
      </div>

      <section className="panel">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Search results</h2>
        </div>
        <div className="grid gap-3 p-4">
          {(searchResults?.chunks ?? []).map((chunk, index) => (
            <article key={chunk.id} className="border border-line bg-surface p-4 text-sm">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <p className="font-semibold text-ink">
                  [{index + 1}] {chunk.citation.title}
                </p>
                <p className="text-xs text-muted">Score {chunk.score.toFixed(3)}</p>
              </div>
              <p className="leading-6 text-ink">{chunk.chunk_text}</p>
              <p className="mt-2 text-xs text-muted">
                {chunk.citation.source_name}
                {chunk.page_number ? ` · page ${chunk.page_number}` : ""}
                {chunk.citation.source_url ? ` · ${chunk.citation.source_url}` : ""}
              </p>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">Documents</h2>
        </div>
        <div className="grid gap-2 p-4">
          {documents.map((document) => (
            <div key={document.id} className="border border-line bg-surface px-3 py-3 text-sm">
              <p className="font-semibold text-ink">{document.title}</p>
              <p className="mt-1 text-xs text-muted">
                {document.symbol ?? "No symbol"} · {document.document_type} · {document.source_name} · {document.status}
              </p>
            </div>
          ))}
        </div>
      </section>
    </section>
  );
}
