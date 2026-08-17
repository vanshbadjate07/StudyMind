import { useEffect, useState } from "react";
import { ApiError, deleteDocument, type DocumentRecord } from "../lib/api";
import { describeErrorReason } from "../lib/errorMessages";
import { ConfirmDialog } from "./ConfirmDialog";
import { DocumentRow } from "./DocumentRow";
import { OverviewDetailPane } from "./OverviewDetailPane";

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
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (selectedId !== null && documents.some((doc) => doc.id === selectedId)) return;
    const mostRecentReady = documents.find((doc) => doc.status === "ready");
    setSelectedId(mostRecentReady?.id ?? documents[0]?.id ?? null);
  }, [documents, selectedId]);

  const pendingDeleteDoc = documents.find((doc) => doc.id === pendingDeleteId) ?? null;
  const selectedDocument = documents.find((doc) => doc.id === selectedId) ?? null;

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
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_1fr]">
        <div className="h-[60vh] overflow-y-auto rounded-xl border border-line bg-surface">
          <ul role="list" className="divide-y divide-line">
            {documents.map((document) => (
              <DocumentRow
                key={document.id}
                document={document}
                summary={summarize(document)}
                selected={document.id === selectedId}
                onSelect={() => setSelectedId(document.id)}
                onDeleteClick={() => {
                  setDeleteError(null);
                  setPendingDeleteId(document.id);
                }}
              />
            ))}
          </ul>
        </div>

        <div className="h-[60vh] overflow-y-auto rounded-xl border border-line bg-surface">
          <OverviewDetailPane document={selectedDocument} />
        </div>
      </div>

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
