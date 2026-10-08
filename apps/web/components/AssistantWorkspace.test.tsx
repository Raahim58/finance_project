import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantWorkspaceProvider, AskAssistant } from "./AssistantWorkspace";
import { AssistantControls } from "./AssistantControls";
import type { RunEvent } from "@/lib/assistant-workspace";
const mocks = vi.hoisted(() => ({
  path: "/companies/OGDC",
  token: "a." + btoa(JSON.stringify({ sub: "user1" })) + ".b",
  list: vi.fn(),
  history: vi.fn(),
  submit: vi.fn(),
  stop: vi.fn(),
  observe: vi.fn(),
  create: vi.fn(),
  portfolios: vi.fn(),
  search: vi.fn(),
  preferences: vi.fn(),
  keys: vi.fn(),
  updatePreferences: vi.fn(),
}));
vi.mock("next/navigation", () => ({ usePathname: () => mocks.path }));
vi.mock("@/lib/api", () => ({
  getToken: () => mocks.token,
  getPortfolios: mocks.portfolios,
  searchInstruments: mocks.search,
  getPreferences: mocks.preferences,
  getLLMKeys: mocks.keys,
  updatePreferences: mocks.updatePreferences,
}));
vi.mock("@/lib/assistant-workspace", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/assistant-workspace")>(),
  listChats: mocks.list,
  getHistory: mocks.history,
  submitRun: mocks.submit,
  stopRun: mocks.stop,
  observeRun: mocks.observe,
  createChat: mocks.create,
  retrySummary: vi.fn(),
  continueChat: vi.fn(),
}));
let callback: (e: RunEvent) => void;
function tree() {
  return (
    <AssistantWorkspaceProvider>
      <div>Page content</div>
      <AskAssistant question="What affects OGDC?">
        Ask about company
      </AskAssistant>
    </AssistantWorkspaceProvider>
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.path = "/companies/OGDC";
  mocks.preferences.mockResolvedValue({ default_llm_provider: "anthropic" });
  mocks.keys.mockResolvedValue([
    { id: "a", provider: "anthropic", default_model: "claude-test", is_active: true },
    { id: "z", provider: "zai", default_model: "glm-test", is_active: true },
    { id: "old", provider: "zai", default_model: "old-model", is_active: true },
    { id: "inactive", provider: "gemini", is_active: false },
  ]);
  mocks.updatePreferences.mockImplementation((prefs) => Promise.resolve(prefs));
  mocks.portfolios.mockResolvedValue([
    { id: "p1", name: "Growth", is_default: true },
  ]);
  mocks.search.mockImplementation((symbol: string) =>
    Promise.resolve([{ id: symbol.toLowerCase(), symbol, name: symbol }]),
  );
  mocks.list.mockResolvedValue({
    items: [
      { id: "c1", title: "Saved research", active_run: null },
      { id: "c2", title: "Other chat", active_run: null },
    ],
    next_cursor: null,
  });
  mocks.history.mockResolvedValue({
    items: [],
    next_cursor: null,
    active_run: null,
    runs: [],
    summary_failure: null,
    summary: null,
  });
  mocks.submit.mockResolvedValue({
    execution_id: "r1",
    conversation_id: "c1",
    status: "queued",
  });
  mocks.observe.mockImplementation(
    (_id, _after, signal: AbortSignal, onEvent) => {
      callback = onEvent;
      return new Promise<void>((resolve) =>
        signal.addEventListener("abort", () => resolve()),
      );
    },
  );
  mocks.stop.mockResolvedValue({ status: "stopped" });
});
afterEach(cleanup);
async function open() {
  fireEvent.click(screen.getByLabelText("Open Assistant"));
  await waitFor(() =>
    expect(
      screen.getByText(/Next message · OGDC · Growth/),
    ).toBeInTheDocument(),
  );
  await waitFor(() =>
    expect(screen.getByText("Saved research")).toBeInTheDocument(),
  );
}
async function send() {
  fireEvent.change(screen.getByLabelText("Message Assistant"), {
    target: { value: "Explain risks" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(mocks.observe).toHaveBeenCalledTimes(1));
}
describe("persistent Assistant", () => {
  it("opens a previous chat over the market brief and closes without generating", async () => {
    mocks.path = "/market";
    render(<AssistantWorkspaceProvider><div>Market brief</div><AssistantControls /></AssistantWorkspaceProvider>);
    fireEvent.click(screen.getByLabelText("Previous chats"));
    fireEvent.click(await screen.findByRole("button", { name: "Other chat" }));
    expect(screen.getByRole("dialog", { name: "Assistant" })).toHaveClass("assistant-market-overlay");
    await waitFor(() => expect(mocks.history).toHaveBeenCalledWith("c2", undefined));
    expect(screen.getByText("Market brief")).toBeInTheDocument();
    expect(mocks.submit).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Close Assistant"));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Open Assistant sidebar"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
  it("switches saved providers without generating and snapshots the next submission", async () => {
    render(tree());
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Switch AI provider" }));
    expect(screen.queryByText(/old-model/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Google Gemini/)).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Z.ai · glm-test" }));
    await waitFor(() => expect(mocks.updatePreferences).toHaveBeenCalledWith({ default_llm_provider: "zai" }));
    await waitFor(() => expect(screen.getByText("glm-test")).toBeInTheDocument());
    expect(mocks.submit).not.toHaveBeenCalled();
    await send();
    expect(mocks.submit.mock.calls[0][4]).toBe("zai");
  });
  it("keeps the previous provider when saving the switch fails", async () => {
    mocks.updatePreferences.mockRejectedValue(new Error("Provider change failed"));
    render(tree());
    await open();
    fireEvent.click(screen.getByRole("button", { name: "Switch AI provider" }));
    fireEvent.click(await screen.findByRole("button", { name: "Z.ai · glm-test" }));
    await screen.findByText("Provider change failed");
    await send();
    expect(mocks.submit.mock.calls[0][4]).toBe("anthropic");
  });
  it("prefills without calling the model", async () => {
    render(tree());
    await open();
    fireEvent.click(screen.getByText("Ask about company"));
    expect(screen.getByLabelText("Message Assistant")).toHaveValue(
      "What affects OGDC?",
    );
    expect(mocks.submit).not.toHaveBeenCalled();
  });
  it("keeps generation and drafts across closure, navigation and expansion", async () => {
    const view = render(tree());
    await open();
    await send();
    fireEvent.change(screen.getByLabelText("Message Assistant"), {
      target: { value: "Next question draft" },
    });
    fireEvent.click(screen.getByLabelText("Close Assistant"));
    mocks.path = "/companies/LUCK";
    view.rerender(tree());
    act(() =>
      callback({
        sequence: 1,
        kind: "text_delta",
        payload: { text: "Provisional answer" },
      }),
    );
    fireEvent.click(screen.getByLabelText("Open Assistant"));
    await waitFor(() =>
      expect(screen.getByText(/Next message · LUCK/)).toBeInTheDocument(),
    );
    expect(screen.getByText("Provisional answer")).toBeInTheDocument();
    expect(screen.getByLabelText("Message Assistant")).toHaveValue(
      "Next question draft",
    );
    fireEvent.click(screen.getByLabelText("Expand Assistant"));
    expect(screen.getByRole("dialog")).toHaveClass("assistant-expanded");
    expect(mocks.stop).not.toHaveBeenCalled();
    expect(mocks.observe).toHaveBeenCalledTimes(1);
    expect(mocks.submit.mock.calls[0][2].instrument_id).toBe("ogdc");
  });
  it("deduplicates replay and only explicitly stops the current run", async () => {
    render(tree());
    await open();
    await send();
    const delta: RunEvent = {
      sequence: 1,
      kind: "text_delta",
      payload: { text: "One copy" },
    };
    act(() => {
      callback(delta);
    });
    act(() => callback(delta));
    expect(screen.getAllByText("One copy")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Stop generating" }));
    await waitFor(() => expect(mocks.stop).toHaveBeenCalledWith("r1"));
  });
  it("switches conversations without stopping and preserves per-chat drafts", async () => {
    render(tree());
    await open();
    fireEvent.change(screen.getByLabelText("Message Assistant"), {
      target: { value: "Draft one" },
    });
    fireEvent.click(screen.getByLabelText("Saved chats"));
    fireEvent.click(screen.getByText("Other chat"));
    fireEvent.change(screen.getByLabelText("Message Assistant"), {
      target: { value: "Draft two" },
    });
    fireEvent.click(screen.getByLabelText("Saved chats"));
    fireEvent.click(screen.getAllByText("Saved research")[0]);
    expect(screen.getByLabelText("Message Assistant")).toHaveValue("Draft one");
    expect(mocks.submit).not.toHaveBeenCalled();
    expect(mocks.stop).not.toHaveBeenCalled();
  });
  it("renders original context, Markdown and saved citations without generation", async () => {
    mocks.history.mockResolvedValue({
      items: [
        {
          id: "m1",
          role: "assistant",
          content: "**Evidence** [Filing](https://example.test/filing)",
          context: {
            page: "company",
            symbol: "OGDC",
            portfolio_name: "Original portfolio",
          },
          outcome: "completed",
          evidence: {
            sources: [
              { title: "Filing", source_url: "https://example.test/filing" },
            ],
          },
        },
      ],
      next_cursor: null,
      active_run: null,
      runs: [],
      summary: null,
    });
    render(tree());
    await open();
    expect(
      await screen.findByText("OGDC · Original portfolio"),
    ).toBeInTheDocument();
    expect(screen.getByText("Evidence").tagName).toBe("STRONG");
    expect(screen.getAllByRole("link", { name: "Filing" })[0]).toHaveAttribute(
      "href",
      "https://example.test/filing",
    );
    expect(mocks.submit).not.toHaveBeenCalled();
  });
});
