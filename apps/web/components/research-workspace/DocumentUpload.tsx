"use client";

import { useRef, useState, type FormEvent } from "react";
import { uploadDocument, type ApiDocument } from "@/lib/api";

export function DocumentUpload({ onUploaded }: { onUploaded: (document: ApiDocument) => void }) {
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [message, setMessage] = useState("");
  const [failed, setFailed] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending.current) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const file = data.get("file");
    if (!(file instanceof File) || !file.size) {
      setFailed(true);
      setMessage("Select a text, Markdown, or PDF file first.");
      return;
    }
    data.set("title", String(data.get("title") ?? "").trim());
    data.set("symbol", String(data.get("symbol") ?? "").trim().toUpperCase());
    data.set("source_name", String(data.get("source_name") ?? "").trim());
    pending.current = true;
    setBusy(true);
    setFailed(false);
    setMessage("");
    try {
      const document = await uploadDocument(data);
      form.reset();
      setMessage(`Document uploaded. Status: ${document.status}.`);
      onUploaded(document);
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }

  return <details className="panel mb-4">
    <summary className="cursor-pointer p-4 text-sm font-semibold">Upload document</summary>
    <form aria-label="Upload source document" onSubmit={submit} className="panel-body">
      <p className="mb-4 text-xs text-muted">Add source text for cited research. Exact financial values come from database queries.</p>
      <fieldset disabled={busy} className="grid gap-4 md:grid-cols-2">
        <label className="field-label">File<input className="field" name="file" type="file" accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf" required /></label>
        <label className="field-label">Title<input className="field" name="title" required /></label>
        <label className="field-label">Type<input className="field" name="document_type" defaultValue="annual_report" required /></label>
        <label className="field-label">Symbol<input className="field uppercase" name="symbol" placeholder="Optional company symbol" /></label>
        <label className="field-label">Source<input className="field" name="source_name" defaultValue="manual" required /></label>
        <button className="btn btn-primary self-end" type="submit">{busy ? "Uploading…" : "Upload and index"}</button>
      </fieldset>
    </form>
    {message ? <p className={`notice m-4 ${failed ? "notice-error" : "notice-good"}`} role={failed ? "alert" : "status"}>{message}</p> : null}
  </details>;
}
