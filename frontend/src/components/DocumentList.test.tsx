import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { DocumentList } from "./DocumentList";

const baseDoc: api.DocumentRecord = {
  id: "doc-1",
  notebook_id: "notebook-1",
  filename: "biology-notes.pdf",
  status: "ready",
  page_count: 12,
  char_count: 5000,
  chunk_count: 8,
  error_reason: null,
  error_detail: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

describe("DocumentList", () => {
  it("shows a loading skeleton while loading", () => {
    render(<DocumentList documents={[]} isLoading onDeleted={vi.fn()} />);
    expect(screen.getByLabelText(/loading documents/i)).toBeInTheDocument();
  });

  it("shows an empty state when there are no documents", () => {
    render(<DocumentList documents={[]} isLoading={false} onDeleted={vi.fn()} />);
    expect(screen.getByText(/no documents yet/i)).toBeInTheDocument();
  });

  it("renders a ready document with its filename and status", () => {
    render(<DocumentList documents={[baseDoc]} isLoading={false} onDeleted={vi.fn()} />);
    expect(screen.getByText("biology-notes.pdf")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText(/12 pages/i)).toBeInTheDocument();
  });

  it("describes in-flight processing states in plain language", () => {
    const processingDoc: api.DocumentRecord = { ...baseDoc, id: "doc-3", status: "processing" };
    const pendingDoc: api.DocumentRecord = { ...baseDoc, id: "doc-4", status: "pending" };
    render(
      <DocumentList
        documents={[processingDoc, pendingDoc]}
        isLoading={false}
        onDeleted={vi.fn()}
      />,
    );

    expect(screen.getByText(/extracting text and indexing/i)).toBeInTheDocument();
    expect(screen.getByText(/queued for processing/i)).toBeInTheDocument();
  });

  it("shows a human-readable reason for a failed document, not a raw code", () => {
    const failedDoc: api.DocumentRecord = {
      ...baseDoc,
      id: "doc-2",
      status: "failed",
      error_reason: "scanned_or_image_only",
    };
    render(<DocumentList documents={[failedDoc]} isLoading={false} onDeleted={vi.fn()} />);

    expect(screen.getByText(/scanned document with no text layer/i)).toBeInTheDocument();
    expect(screen.queryByText("scanned_or_image_only")).not.toBeInTheDocument();
  });

  it("asks for confirmation before deleting, and does not delete on cancel", async () => {
    const deleteSpy = vi.spyOn(api, "deleteDocument");
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    render(<DocumentList documents={[baseDoc]} isLoading={false} onDeleted={onDeleted} />);

    await user.click(screen.getByLabelText(/delete biology-notes\.pdf/i));
    expect(screen.getByText(/delete this document/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(deleteSpy).not.toHaveBeenCalled();
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("deletes the document after confirmation", async () => {
    vi.spyOn(api, "deleteDocument").mockResolvedValue(undefined);
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    render(<DocumentList documents={[baseDoc]} isLoading={false} onDeleted={onDeleted} />);

    await user.click(screen.getByLabelText(/delete biology-notes\.pdf/i));
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith("doc-1"));
  });

  it("shows an error message if deletion fails, and keeps the document listed", async () => {
    vi.spyOn(api, "deleteDocument").mockRejectedValue(new api.ApiError(500, "Server error."));
    const onDeleted = vi.fn();
    const user = userEvent.setup();
    render(<DocumentList documents={[baseDoc]} isLoading={false} onDeleted={onDeleted} />);

    await user.click(screen.getByLabelText(/delete biology-notes\.pdf/i));
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/server error/i);
    expect(onDeleted).not.toHaveBeenCalled();
    expect(screen.getByText("biology-notes.pdf")).toBeInTheDocument();
  });
});
