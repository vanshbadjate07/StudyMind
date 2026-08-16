import { useState } from "react";
import { ApiError, deleteDocument, type DocumentRecord } from "../lib/api";
import { describeErrorReason } from "../lib/errorMessages";
import { ConfirmDialog } from "./ConfirmDialog";
import { DocumentStatusBadge } from "./DocumentStatusBadge";

interface DocumentListProps {
  documents: DocumentRecord[];
  isLoading: boolean;
  onDeleted: (documentId: string) => void;
}

function summarize(document: DocumentRecord): string | null {
  switch (document.status) {
    case "ready": {
      const parts: string[] = [];
      if (document.page_count) {
        parts.push(`${document.page_count} page${document.page_count === 1 ? "" : "s"}`);
      }
      if (document.chunk_count) {
        parts.push(`${document.chunk_count} chunks indexed`);
      }
      return parts.length > 0 ? parts.join(" · ") : null;
    }
    case "failed":
      return describeErrorReason(document.error_reason);
    case "processing":
      return "Extracting text and indexing for search…";
    case "pending":
      return "Queued for processing…";
    default:
      return null;
  }
}

export function DocumentList({ documents, isLoading, onDeleted }: DocumentListProps) {
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const pendingDeleteDoc = documents.find((doc) => doc.id === pendingDeleteId) ?? null;

  const confirmDelete = async () => {
    if (!pendingDeleteId) return;
    setIsDeleting(true);
    try {
      await deleteDocument(pendingDeleteId);
      onDeleted(pendingDeleteId);
      setPendingDeleteId(null);
    } catch (err) {
      setDeleteError(err instanceof ApiError ? err.message : "Couldn't delete this document.");
    } finally {
      setIsDeleting(false);
    }
  };

  if (isLoading) {
    return <DocumentListSkeleton />;
  }

  if (documents.length === 0) {
    return (
      <div
        role="status"
        className="rounded-xl border border-dashed border-line-strong p-10 text-center"
      >
        <p className="text-sm font-medium text-ink">No documents yet</p>
        <p className="mt-1 text-sm text-ink-muted">Upload a PDF above to get started.</p>
      </div>
    );
  }

  return (
    <>
      <ul role="list" className="divide-y divide-line rounded-xl border border-line bg-surface">
        {documents.map((document) => {
          const summary = summarize(document);
          const isFailed = document.status === "failed";
          return (
            <li key={document.id} className="flex items-start gap-4 p-4">
              <DocumentIcon failed={isFailed} />
              <div className="min-w-0 flex-1 pt-0.5">
                <p className="truncate text-sm font-medium text-ink">{document.filename}</p>
                {summary && (
                  <p
                    className={`mt-0.5 truncate text-xs ${isFailed ? "text-status-failed" : "text-ink-muted"}`}
                  >
                    {summary}
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-3 pt-0.5">
                <DocumentStatusBadge status={document.status} />
                <button
                  type="button"
                  onClick={() => {
                    setDeleteError(null);
                    setPendingDeleteId(document.id);
                  }}
                  aria-label={`Delete ${document.filename}`}
                  className="rounded-lg p-2 text-ink-faint transition-colors hover:bg-paper hover:text-status-failed"
                >
                  <TrashIcon />
                </button>
              </div>
            </li>
          );
        })}
      </ul>

      {deleteError && (
        <p role="alert" className="mt-3 text-sm text-status-failed">
          {deleteError}
        </p>
      )}

      <ConfirmDialog
        open={pendingDeleteDoc !== null}
        title="Delete this document?"
        description={
          pendingDeleteDoc
            ? `"${pendingDeleteDoc.filename}" and everything generated from it will be permanently removed.`
            : ""
        }
        confirmLabel={isDeleting ? "Deleting…" : "Delete"}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDeleteId(null)}
      />
    </>
  );
}

function DocumentListSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading documents">
      {Array.from({ length: 3 }).map((_, index) => (
        <div key={index} className="h-16 animate-pulse rounded-xl bg-line/60" />
      ))}
    </div>
  );
}

function DocumentIcon({ failed }: { failed: boolean }) {
  return (
    <span
      className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${
        failed ? "bg-status-failed-subtle" : "bg-brand-subtle"
      }`}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        className={`h-5 w-5 ${failed ? "text-status-failed" : "text-brand-ink"}`}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"
        />
        <path strokeLinecap="round" strokeLinejoin="round" d="M14 3v5h5" />
      </svg>
    </span>
  );
}

function TrashIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      className="h-4 w-4"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-.6 12.2A2 2 0 0 1 14.4 21H9.6a2 2 0 0 1-2-1.8L7 7h10Z"
      />
    </svg>
  );
}
