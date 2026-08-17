import type { DocumentRecord } from "../lib/api";
import { OverviewPanel } from "./OverviewPanel";

interface OverviewDetailPaneProps {
  document: DocumentRecord | null;
}

export function OverviewDetailPane({ document }: OverviewDetailPaneProps) {
  if (document === null) {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <p className="text-sm text-ink-muted">Select a document to see its overview.</p>
      </div>
    );
  }

  if (document.status !== "ready") {
    return (
      <div className="flex h-full items-center justify-center p-6 text-center">
        <p className="text-sm text-ink-muted">
          {document.status === "failed"
            ? "This document failed to process, so it has no overview."
            : "Still processing — the overview will appear once this document is ready."}
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="border-b border-line px-4 py-3">
        <p className="truncate text-sm font-semibold text-ink">{document.filename}</p>
      </div>
      <OverviewPanel documentId={document.id} />
    </div>
  );
}
