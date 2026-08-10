import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceBadge } from "./EvidenceBadge";

describe("EvidenceBadge", () => {
  it("shows freshness provenance", () => {
    render(<EvidenceBadge asOf="2026-08-07" source="dps" />);
    expect(screen.getByText(/2026-08-07/)).toBeInTheDocument();
    expect(screen.getByText(/dps/)).toBeInTheDocument();
  });

  it("prioritizes warnings", () => {
    render(<EvidenceBadge warning="Data is stale" />);
    expect(screen.getByText("Data is stale")).toBeInTheDocument();
  });
});
