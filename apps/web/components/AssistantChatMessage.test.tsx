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
