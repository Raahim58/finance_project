import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DocumentUpload } from "./DocumentUpload";

const upload = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({ uploadDocument: upload }));
afterEach(cleanup);
beforeEach(() => { upload.mockReset(); });

function fill() {
  fireEvent.change(screen.getByLabelText("File"), { target: { files: [new File(["Source text"], "report.txt", { type: "text/plain" })] } });
  // jsdom does not copy synthetic files into FormData; supply the same browser payload.
  const NativeFormData = globalThis.FormData;
  vi.spyOn(globalThis, "FormData").mockImplementation(function(form?: HTMLFormElement) {
    const data = new NativeFormData(form);
    data.set("file", new File(["Source text"], "report.txt", { type: "text/plain" }));
    return data;
  });
  fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Annual report" } });
  fireEvent.change(screen.getByLabelText("Symbol"), { target: { value: " ffc " } });
}
afterEach(() => vi.restoreAllMocks());

describe("Research document upload", () => {
  it("rejects a missing file without sending a request", () => {
    render(<DocumentUpload onUploaded={vi.fn()} />);
    fireEvent.click(screen.getByText("Upload document"));
    fireEvent.submit(screen.getByRole("form", { name: "Upload source document" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Select a text, Markdown, or PDF file first.");
    expect(upload).not.toHaveBeenCalled();
  });

  it("submits source metadata once and refreshes only after success", async () => {
    const document = { id: "upload-1", status: "ready" };
    let resolve!: (value: typeof document) => void;
    upload.mockReturnValue(new Promise(done => { resolve = done; }));
    const onUploaded = vi.fn();
    render(<DocumentUpload onUploaded={onUploaded} />);
    fireEvent.click(screen.getByText("Upload document"));
    fill();
    const form = screen.getByRole("form", { name: "Upload source document" });
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(upload).toHaveBeenCalledTimes(1);
    const payload = upload.mock.calls[0][0] as FormData;
    expect(payload.get("title")).toBe("Annual report");
    expect(payload.get("symbol")).toBe("FFC");
    expect(payload.get("document_type")).toBe("annual_report");
    expect(payload.get("source_name")).toBe("manual");
    expect((payload.get("file") as File).name).toBe("report.txt");
    expect(screen.getByRole("button", { name: "Uploading…" })).toBeDisabled();
    expect(onUploaded).not.toHaveBeenCalled();
    resolve(document);
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(document));
    expect(screen.getByRole("status")).toHaveTextContent("Status: ready");
    expect(screen.getByLabelText("Title")).toHaveValue("");
  });

  it("keeps inputs after failure and does not refresh", async () => {
    upload.mockRejectedValue(new Error("Unsupported file"));
    const onUploaded = vi.fn();
    render(<DocumentUpload onUploaded={onUploaded} />);
    fireEvent.click(screen.getByText("Upload document"));
    fill();
    fireEvent.submit(screen.getByRole("form", { name: "Upload source document" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Unsupported file");
    expect(screen.getByLabelText("Title")).toHaveValue("Annual report");
    expect(screen.getByRole("button", { name: "Upload and index" })).toBeEnabled();
    expect(onUploaded).not.toHaveBeenCalled();
  });
});
