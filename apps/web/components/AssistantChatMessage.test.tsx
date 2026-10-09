import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatMessageView, outcomeLabel } from "./AssistantChatMessage";
import { sumTokenUsage, tokenUsageOf, type ChatMessage } from "@/lib/assistant-workspace";
describe("saved provider failure", () => {
  it("shows the actual overload cause after history reload", () => {
    render(<ChatMessageView message={{id:"failed",role:"assistant",content:"No answer was completed.",context:{page:"workspace"},created_at:"2026-10-03T00:00:00Z",outcome:"failed",evidence:{provisional:true,error_code:"provider_overloaded"}}}/>);
    expect(screen.getByText(/Z.ai reports temporary overload/)).toBeInTheDocument();
  });
  it("distinguishes rate limits and missing balance", () => {
    expect(outcomeLabel("failed","provider_rate_limited")).toContain("request limit");
    expect(outcomeLabel("failed","provider_quota_exhausted")).toContain("insufficient balance");
  });
});

describe("calculated allocation candidates", () => {
  it("keeps a feasible candidate visibly distinct from full IPS acceptance", () => {
    render(<ChatMessageView message={{id:"candidate",role:"assistant",content:"Calculated candidate",context:{page:"workspace"},created_at:"2026-10-04T00:00:00Z",outcome:"completed",evidence:{synthesis:{allocation_check:{trade_feasibility:"valid",IPS_status:"breach_and_incomplete",checks:{ips_compliance:{status:"BREACH"}},evidence_readiness:{actionable_recommendation_eligible:false}}}}}}/>);
    expect(screen.getByText(/not fully IPS compliant: breach and incomplete/)).toBeInTheDocument();
    expect(screen.getByText(/breaches the recorded investment policy/)).toBeInTheDocument();
  });
});

const answer = (usage?: Record<string, unknown>, role = "assistant"): ChatMessage => ({
  id: "m", role, content: "Answer", context: { page: "workspace" }, created_at: "2026-10-07T00:00:00Z",
  outcome: "completed", evidence: usage ? { synthesis: { token_usage: usage } } : {},
});

describe("token usage", () => {
  it("shows input, cached, output and model calls under an assistant answer", () => {
    render(<ChatMessageView message={answer({ input_tokens: 12345, output_tokens: 678, cache_read_tokens: 2000, model_calls: 2, reported_by_provider: true })}/>);
    expect(screen.getByTestId("token-usage")).toHaveTextContent("Input 12,345 (2,000 cached) · Output 678 · 2 model calls");
  });
  it("is honest when the provider did not report all usage", () => {
    render(<ChatMessageView message={answer({ input_tokens: 10, output_tokens: 5, model_calls: 1, reported_by_provider: false })}/>);
    expect(screen.getByText(/not fully reported by the provider · 1 model call$/)).toBeInTheDocument();
  });
  it("shows nothing for answers without stored usage and for user messages", () => {
    const { container } = render(<ChatMessageView message={answer(undefined)}/>);
    expect(container.querySelector(".assistant-tokens")).toBeNull();
    expect(tokenUsageOf(answer({ input_tokens: 1, output_tokens: 1 }, "user"))).toBeNull();
  });
  it("sums loaded answers and counts unreported ones", () => {
    const total = sumTokenUsage([
      answer({ input_tokens: 100, output_tokens: 10, cache_read_tokens: 5, model_calls: 1, reported_by_provider: true }),
      answer({ input_tokens: 50, output_tokens: 20, model_calls: 3, reported_by_provider: false }),
      answer(undefined),
    ]);
    expect(total).toEqual({ input: 150, output: 30, cached: 5, calls: 4, answers: 2, unreported: 1 });
  });
});
