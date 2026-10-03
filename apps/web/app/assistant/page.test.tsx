import { render, waitFor, cleanup } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import AssistantPage from "./page";
const open = vi.fn(),
  replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams("question=Explain+OGDC"),
}));
vi.mock("@/components/AssistantWorkspace", () => ({
  useAssistantWorkspace: () => ({ open }),
}));
afterEach(cleanup);
it("opens and prefills the persistent drawer, then redirects without submitting", async () => {
  render(<AssistantPage />);
  await waitFor(() => expect(open).toHaveBeenCalledWith("Explain OGDC"));
  expect(replace).toHaveBeenCalledWith("/dashboard");
});
