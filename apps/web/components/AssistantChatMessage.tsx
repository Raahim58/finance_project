"use client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "@/lib/assistant-workspace";
export function outcomeLabel(status: string, error?: string | null) {
  return (
    (
      {
        stopped: "Stopped",
        timeout: "Timed out",
        incomplete: "Incomplete answer — output limit reached",
        interrupted:
          "Interrupted — the server restarted during a provider request",
        limited: "Question limit reached",
        failed: "Could not complete this answer",
        synthesis_unavailable: "Answer unavailable",
      } as Record<string, string>
    )[status] ?? (error ? "Answer unavailable" : "")
  );
}
export function Markdown({ text }: { text: string }) {
  return (
    <div className="assistant-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
export function ChatMessageView({ message }: { message: ChatMessage }) {
  const context = message.context;
  const sources = message.evidence?.sources ?? [];
  const warnings = essentialWarnings(message.evidence?.synthesis);
  return (
    <article
      className={`assistant-message ${message.role === "user" ? "assistant-user" : "assistant-answer"}`}
    >
      <div className="assistant-message-label">
        <strong>{message.role === "user" ? "You" : "Assistant"}</strong>
        <small>
          {[context.symbol, context.portfolio_name].filter(Boolean).join(" · ")}
        </small>
      </div>
      <Markdown text={message.content} />
      {message.outcome && message.outcome !== "completed" ? (
        <p className="assistant-warning">
          {outcomeLabel(message.outcome)}
          {message.evidence?.provisional
            ? " · Partial answer wasn’t verified"
            : ""}
        </p>
      ) : null}
      {warnings.map((warning) => (
        <p key={warning} className="assistant-warning">
          {warning}
        </p>
      ))}
      {sources.length ? (
        <details className="assistant-sources">
          <summary>Sources ({sources.length})</summary>
          {sources.map((source, index) => (
            <div key={index}>
              {typeof source.source_url === "string" &&
              /^https?:\/\//i.test(source.source_url) ? (
                <a
                  href={source.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {String(source.title ?? source.source_name ?? "Source")}
                </a>
              ) : (
                <span>
                  {String(
                    source.title ?? source.source_name ?? "Database evidence",
                  )}
                </span>
              )}
              {source.page_number ? ` · p. ${source.page_number}` : null}
            </div>
          ))}
        </details>
      ) : null}
    </article>
  );
}

function essentialWarnings(synthesis?: Record<string, unknown>): string[] {
  const allocation = synthesis?.allocation_check as
    | {
        checks?: {
          price_freshness?: { status: string };
          ips_compliance?: { status: string };
        };
        evidence_readiness?: { actionable_recommendation_eligible?: boolean };
      }
    | undefined;
  const warnings: string[] = [];
  if (allocation?.checks?.price_freshness?.status === "stale")
    warnings.push("Prices are stale. Verify current prices before acting.");
  if (allocation?.checks?.price_freshness?.status === "unavailable")
    warnings.push("Current price evidence is unavailable.");
  if (allocation?.checks?.ips_compliance?.status === "BREACH")
    warnings.push(
      "The proposed allocation breaches the recorded investment policy.",
    );
  if (
    allocation?.evidence_readiness?.actionable_recommendation_eligible === false
  )
    warnings.push("Evidence is insufficient for an actionable recommendation.");
  return warnings;
}
