import type { DocumentRecord } from "../lib/api";
import { DocumentStatusBadge } from "./DocumentStatusBadge";
import { OverviewPanel } from "./OverviewPanel";

interface DocumentRowProps {
  document: DocumentRecord;
  summary: string | null;
  onDeleteClick: () => void;
}

export function DocumentRow({ document, summary, onDeleteClick }: DocumentRowProps) {
  const isFailed = document.status === "failed";
  const isReady = document.status === "ready";

  return (
    <li>
      <div className="flex items-start gap-4 p-4">
        <DocumentIcon failed={isFailed} />
        <div className="min-w-0 flex-1 pt-0.5">
          <p className="truncate text-sm font-medium text-ink">{document.filename}</p>
          {summary && (
            <p className={`mt-0.5 truncate text-xs ${isFailed ? "text-status-failed" : "text-ink-muted"}`}>
              {summary}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3 pt-0.5">
          <DocumentStatusBadge status={document.status} />
          <button
            type="button"
            onClick={onDeleteClick}
            aria-label={`Delete ${document.filename}`}
            className="rounded-lg p-2 text-ink-faint transition-colors hover:bg-paper hover:text-status-failed"
          >
            <TrashIcon />
          </button>
        </div>
      </div>
      {isReady && <OverviewPanel documentId={document.id} />}
    </li>
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
