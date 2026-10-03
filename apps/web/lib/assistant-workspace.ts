import { API_BASE_URL, getToken, request } from "@/lib/api/client";
import type { AssistantResult } from "@/lib/api";
export type MessageContext = {
  page: "workspace" | "company" | "portfolio";
  instrument_id?: string | null;
  symbol?: string | null;
  company_name?: string | null;
  portfolio_id?: string | null;
  portfolio_name?: string | null;
};
export type ChatMessage = {
  id: string;
  role: string;
  content: string;
  context: MessageContext;
  execution_id?: string | null;
  outcome?: string | null;
  created_at: string;
  evidence?: {
    provisional?: boolean;
    sources?: Array<Record<string, unknown>>;
    synthesis?: Record<string, unknown>;
  };
};
export type ChatRun = {
  execution_id: string;
  status: string;
  error_code?: string | null;
};
export type Conversation = {
  id: string;
  title: string;
  latest_activity: string;
  active_run: ChatRun | null;
  summary_failure?: string | null;
};
export type History = {
  items: ChatMessage[];
  next_cursor: string | null;
  active_run: ChatRun | null;
  runs: ChatRun[];
  summary_failure: string | null;
  summary: {
    version: number;
    text: string;
    covered_through_message_id: string;
  } | null;
};
export type RunEvent = {
  sequence: number;
  kind: string;
  payload: {
    text?: string;
    status?: string;
    error_code?: string | null;
    response?: AssistantResult | null;
  };
};
export const listChats = (cursor?: string) =>
  request<{ items: Conversation[]; next_cursor: string | null }>(
    `/assistant/workspace/conversations${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    {},
    0,
  );
export const createChat = () =>
  request<{ id: string; title: string }>("/assistant/conversations", {
    method: "POST",
    body: JSON.stringify({ title: "New chat" }),
  });
export const getHistory = (id: string, cursor?: string) =>
  request<History>(
    `/assistant/workspace/conversations/${id}/messages${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ""}`,
    {},
    0,
  );
export const submitRun = (
  id: string,
  question: string,
  context: MessageContext,
  clientRequestId: string,
) =>
  request<ChatRun & { conversation_id: string }>("/assistant/runs", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: id,
      question,
      client_request_id: clientRequestId,
      page_context: {
        page: context.page,
        instrument_id: context.instrument_id ?? null,
        portfolio_id:
          context.page === "portfolio" ? context.portfolio_id : null,
      },
    }),
  });
export const stopRun = (id: string) =>
  request<{ status: string }>(`/assistant/runs/${id}/cancel`, {
    method: "POST",
  });
export const retrySummary = (id: string) =>
  request(`/assistant/workspace/conversations/${id}/retry-summary`, {
    method: "POST",
  });
export const continueChat = (id: string) =>
  request<{ id: string; title: string }>(
    `/assistant/workspace/conversations/${id}/continue`,
    { method: "POST" },
  );

// Authenticated fetch SSE. The observer's AbortController never cancels a run.
export async function observeRun(
  id: string,
  after: number,
  signal: AbortSignal,
  onEvent: (event: RunEvent) => void,
  onSnapshot: (snapshot: RunEvent["payload"]) => void,
) {
  const response = await fetch(
    `${API_BASE_URL}/assistant/runs/${id}/events?after=${after}`,
    {
      headers: { Authorization: `Bearer ${getToken() ?? ""}` },
      signal,
      cache: "no-store",
    },
  );
  if (!response.ok || !response.body)
    throw new Error(`Could not reconnect (${response.status})`);
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      buffer += decoder
        .decode(part.value, { stream: true })
        .replace(/\r\n/g, "\n");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const data = frame
          .split("\n")
          .filter((line) => line.startsWith("data:"))
          .map((line) => line.slice(5).trimStart())
          .join("\n");
        if (!data) continue;
        const parsed = JSON.parse(data);
        if (frame.includes("event: snapshot")) onSnapshot(parsed);
        else onEvent(parsed);
      }
    }
  } finally {
    reader.releaseLock();
  }
}
