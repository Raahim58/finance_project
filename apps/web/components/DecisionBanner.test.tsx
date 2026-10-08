import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DecisionBanner } from "./WorkspacePage";

describe("mandate evidence state", () => {
  it("does not turn a failed compliance read into a zero-count breach", () => {
    render(<DecisionBanner compliance={null} />);
    expect(screen.getByText("Not fully evaluated")).toBeInTheDocument();
    expect(screen.getByText(/mandate status is unknown/)).toBeInTheDocument();
    expect(screen.queryByText("Mandate breach")).not.toBeInTheDocument();
    expect(screen.queryByText(/0 hard mandate/)).not.toBeInTheDocument();
  });
});
