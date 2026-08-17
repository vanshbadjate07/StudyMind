import type { DocumentRecord } from "../lib/api";
import { DocumentStatusBadge } from "./DocumentStatusBadge";

interface DocumentRowProps {
  document: DocumentRecord;
  summary: string | null;
  selected: boolean;
  onSelect: () => void;
  onDeleteClick: () => void;
}

export function DocumentRow({ document, summary, selected, onSelect, onDeleteClick }: DocumentRowProps) {
  const isFailed = document.status === "failed";

  return (
    <li>
      <div
        role="button"
        tabIndex={0}
        onClick={onSelect}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onSelect();
          }
        }}
        aria-pressed={selected}
        className={`flex cursor-pointer items-start gap-3 p-3 transition-colors ${
          selected ? "bg-brand-subtle" : "hover:bg-paper"
        }`}
      >
        <DocumentIcon failed={isFailed} />
        <div className="min-w-0 flex-1 pt-0.5">
          <p className="truncate text-sm font-medium text-ink">{document.filename}</p>
          {summary && (
            <p className={`mt-0.5 truncate text-xs ${isFailed ? "text-status-failed" : "text-ink-muted"}`}>
              {summary}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-0.5">
          <DocumentStatusBadge status={document.status} />
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              onDeleteClick();
            }}
            aria-label={`Delete ${document.filename}`}
            className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-surface hover:text-status-failed"
          >
            <TrashIcon />
          </button>
        </div>
      </div>
    </li>
  );
}

function DocumentIcon({ failed }: { failed: boolean }) {
  return (
    <span
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
        failed ? "bg-status-failed-subtle" : "bg-brand-subtle"
      }`}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        className={`h-4 w-4 ${failed ? "text-status-failed" : "text-brand-ink"}`}
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
