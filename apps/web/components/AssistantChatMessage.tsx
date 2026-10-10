"use client";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { tokenUsageOf, type ChatMessage, type TokenUsage } from "@/lib/assistant-workspace";
export function outcomeLabel(status: string, error?: string | null) {
  const providerErrors: Record<string, string> = {
    provider_overloaded: "Z.ai reports temporary overload (1305). Try again later.",
    provider_rate_limited: "Z.ai’s request limit was reached. Try again later.",
    provider_quota_exhausted: "Z.ai reports insufficient balance or no resource package.",
    provider_http_429: "The model provider rejected this request (429). Try again later.",
  };
  if (error && providerErrors[error]) return providerErrors[error];
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
const number = new Intl.NumberFormat("en-US");
export function TokenLine({ usage }: { usage: TokenUsage }) {
  const calls = usage.model_calls ?? 0;
  const callText = `${calls} model call${calls === 1 ? "" : "s"}`;
  if (usage.reported_by_provider === false)
    return <p className="assistant-tokens">Token usage not fully reported by the provider · {callText}</p>;
  const cached = usage.cache_read_tokens ? ` (${number.format(usage.cache_read_tokens)} cached)` : "";
  return (
    <p className="assistant-tokens" data-testid="token-usage">
      Input {number.format(usage.input_tokens)}{cached} · Output {number.format(usage.output_tokens)} · {callText}
    </p>
  );
}
export function ChatMessageView({ message }: { message: ChatMessage }) {
  const context = message.context;
  const sources = message.evidence?.sources ?? [];
  const warnings = essentialWarnings(message.evidence?.synthesis);
  const usage = tokenUsageOf(message);
  return (
    <article
      className={`assistant-message ${message.role === "user" ? "assistant-user" : "assistant-answer"}`}
    >
      <div className="assistant-message-label">
        {message.role === "user" ? <strong className="sr-only">You</strong> : <><span className="assistant-avatar" aria-hidden="true">R</span><strong className="sr-only">Assistant</strong></>}
        {message.role === "user" ? null : <small>
          {[context.symbol, context.portfolio_name].filter(Boolean).join(" · ")}
        </small>}
      </div>
      <Markdown text={message.content} />
      {message.role === "assistant" && message.outcome && message.outcome !== "completed" ? (
        <p className="assistant-warning">
          {outcomeLabel(message.outcome, message.evidence?.error_code)}
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
      {usage ? <TokenLine usage={usage} /> : null}
    </article>
  );
}

function essentialWarnings(synthesis?: Record<string, unknown>): string[] {
  const allocation = synthesis?.allocation_check as
    | {
        trade_feasibility?: string;
        IPS_status?: string;
        checks?: {
          price_freshness?: { status: string };
          ips_compliance?: { status: string };
        };
        evidence_readiness?: { actionable_recommendation_eligible?: boolean };
      }
    | undefined;
  const warnings: string[] = [];
  const unverified = (synthesis?.citation_resolution as { unverified_number_lines?: number } | undefined)?.unverified_number_lines;
  if (unverified) warnings.push("Some figures cite sources that can’t be machine-checked. Verify them against the sources.");
  if (allocation?.trade_feasibility === "valid" && allocation.IPS_status && allocation.IPS_status !== "pass")
    warnings.push(`Calculated candidate, not fully IPS compliant: ${allocation.IPS_status.replaceAll("_", " ")}.`);
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
