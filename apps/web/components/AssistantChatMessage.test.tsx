import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatMessageView, outcomeLabel } from "./AssistantChatMessage";
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
