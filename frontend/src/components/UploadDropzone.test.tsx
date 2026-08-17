import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { UploadDropzone } from "./UploadDropzone";

describe("UploadDropzone", () => {
  it("rejects an unsupported file type without calling the API", async () => {
    const uploadSpy = vi.spyOn(api, "uploadDocument");
    const onUploaded = vi.fn();
    render(<UploadDropzone notebookId="notebook-1" onUploaded={onUploaded} />);

    const input = screen.getByLabelText(/upload a document/i);
    const file = new File(["hello"], "photo.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/unsupported file type/i);
    expect(uploadSpy).not.toHaveBeenCalled();
    expect(onUploaded).not.toHaveBeenCalled();
  });

  it("rejects an oversized PDF without calling the API", async () => {
    const uploadSpy = vi.spyOn(api, "uploadDocument");
    render(<UploadDropzone notebookId="notebook-1" onUploaded={vi.fn()} />);

    const input = screen.getByLabelText(/upload a document/i);
    const oversizedBytes = new Uint8Array(51 * 1024 * 1024);
    const file = new File([oversizedBytes], "huge.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/50MB/i);
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it("rejects an empty file without calling the API", async () => {
    const uploadSpy = vi.spyOn(api, "uploadDocument");
    render(<UploadDropzone notebookId="notebook-1" onUploaded={vi.fn()} />);

    const input = screen.getByLabelText(/upload a document/i);
    const file = new File([], "empty.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/empty/i);
    expect(uploadSpy).not.toHaveBeenCalled();
  });

  it("uploads a valid PDF and calls onUploaded with the server response", async () => {
    const fakeDocument: api.DocumentRecord = {
      id: "abc-123",
      notebook_id: "notebook-1",
      filename: "notes.pdf",
      status: "pending",
      page_count: null,
      char_count: null,
      chunk_count: null,
      error_reason: null,
      error_detail: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    vi.spyOn(api, "uploadDocument").mockResolvedValue(fakeDocument);
    const onUploaded = vi.fn();
    render(<UploadDropzone notebookId="notebook-1" onUploaded={onUploaded} />);

    const input = screen.getByLabelText(/upload a document/i);
    const file = new File(["%PDF-1.4 fake content"], "notes.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(fakeDocument));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a visible error message when the upload fails server-side", async () => {
    vi.spyOn(api, "uploadDocument").mockRejectedValue(new api.ApiError(400, "File does not look like a valid PDF."));
    render(<UploadDropzone notebookId="notebook-1" onUploaded={vi.fn()} />);

    const input = screen.getByLabelText(/upload a document/i);
    const file = new File(["not really a pdf"], "fake.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    expect(await screen.findByRole("alert")).toHaveTextContent(/does not look like a valid pdf/i);
  });

  it("uploads multiple selected PDFs, calling onUploaded once per file", async () => {
    const makeDocument = (id: string, filename: string): api.DocumentRecord => ({
      id,
      notebook_id: "notebook-1",
      filename,
      status: "pending",
      page_count: null,
      char_count: null,
      chunk_count: null,
      error_reason: null,
      error_detail: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    vi.spyOn(api, "uploadDocument").mockImplementation(async (_notebookId, file) =>
      makeDocument(`${file.name}-id`, file.name),
    );
    const onUploaded = vi.fn();
    render(<UploadDropzone notebookId="notebook-1" onUploaded={onUploaded} />);

    const input = screen.getByLabelText(/upload a document/i);
    const fileA = new File(["%PDF-1.4 a"], "a.pdf", { type: "application/pdf" });
    const fileB = new File(["%PDF-1.4 b"], "b.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [fileA, fileB] } });

    await waitFor(() => expect(onUploaded).toHaveBeenCalledTimes(2));
    expect(onUploaded).toHaveBeenCalledWith(makeDocument("a.pdf-id", "a.pdf"));
    expect(onUploaded).toHaveBeenCalledWith(makeDocument("b.pdf-id", "b.pdf"));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("uploads valid files even when one file in the same batch is rejected", async () => {
    const fakeDocument: api.DocumentRecord = {
      id: "good-id",
      notebook_id: "notebook-1",
      filename: "good.pdf",
      status: "pending",
      page_count: null,
      char_count: null,
      chunk_count: null,
      error_reason: null,
      error_detail: null,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    vi.spyOn(api, "uploadDocument").mockResolvedValue(fakeDocument);
    const onUploaded = vi.fn();
    render(<UploadDropzone notebookId="notebook-1" onUploaded={onUploaded} />);

    const input = screen.getByLabelText(/upload a document/i);
    const badFile = new File(["hello"], "photo.png", { type: "image/png" });
    const goodFile = new File(["%PDF-1.4 good"], "good.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [badFile, goodFile] } });

    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(fakeDocument));
    expect(await screen.findByRole("alert")).toHaveTextContent(/unsupported file type/i);
  });
});
