import { useEffect, useRef, useState } from "react";
import type { NotebookRecord } from "../lib/api";
import { GOAL_LABELS } from "../lib/goalLabels";
import { notebookAccent } from "../lib/notebookAccent";
import { formatRelativeTime } from "../lib/relativeTime";

interface NotebookCardProps {
  notebook: NotebookRecord;
  onOpen: () => void;
  onRename: (name: string) => Promise<void>;
  onDeleteClick: () => void;
}

export function NotebookCard({ notebook, onOpen, onRename, onDeleteClick }: NotebookCardProps) {
  const [isRenaming, setIsRenaming] = useState(false);
  const [draftName, setDraftName] = useState(notebook.name);
  const inputRef = useRef<HTMLInputElement>(null);
  const accent = notebookAccent(notebook.id);

  useEffect(() => {
    if (isRenaming) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isRenaming]);

  const commitRename = async () => {
    const trimmed = draftName.trim();
    setIsRenaming(false);
    if (trimmed && trimmed !== notebook.name) {
      await onRename(trimmed);
    } else {
      setDraftName(notebook.name);
    }
  };

  return (
    <div className="group relative flex flex-col rounded-xl border border-line bg-surface p-4 transition-colors hover:border-line-strong">
      <span
        className={`flex h-9 w-9 items-center justify-center rounded-lg ${accent.bg} ${accent.text}`}
      >
        <NotebookIcon />
      </span>

      {isRenaming ? (
        <input
          ref={inputRef}
          value={draftName}
          onChange={(event) => setDraftName(event.target.value)}
          onBlur={() => void commitRename()}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              void commitRename();
            } else if (event.key === "Escape") {
              event.preventDefault();
              setDraftName(notebook.name);
              setIsRenaming(false);
            }
          }}
          aria-label="Notebook name"
          className="mt-3 w-full rounded-md border border-brand bg-paper px-1.5 py-1 text-sm font-semibold text-ink focus:outline-none"
        />
      ) : (
        <button type="button" onClick={onOpen} className="flex flex-1 flex-col items-start text-left">
          <p className="mt-3 line-clamp-2 text-sm font-semibold text-ink">{notebook.name}</p>
          {notebook.goal_type && (
            <span className="mt-2 rounded-full border border-line px-2 py-0.5 text-[11px] font-medium text-ink-muted">
              {GOAL_LABELS[notebook.goal_type]}
            </span>
          )}
          <span className="mt-auto pt-3 text-[11px] text-ink-faint">
            Updated {formatRelativeTime(notebook.updated_at)}
          </span>
        </button>
      )}

      {!isRenaming && (
        <div className="absolute top-3 right-3 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
          <button
            type="button"
            onClick={() => setIsRenaming(true)}
            aria-label={`Rename ${notebook.name}`}
            className="rounded-lg bg-surface p-1.5 text-ink-faint transition-colors hover:bg-paper hover:text-ink"
          >
            <PencilIcon />
          </button>
          <button
            type="button"
            onClick={onDeleteClick}
            aria-label={`Delete ${notebook.name}`}
            className="rounded-lg bg-surface p-1.5 text-ink-faint transition-colors hover:bg-paper hover:text-status-failed"
          >
            <TrashIcon />
          </button>
        </div>
      )}
    </div>
  );
}

function NotebookIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className="h-4.5 w-4.5"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"
      />
      <path strokeLinecap="round" strokeLinejoin="round" d="M14 3v5h5" />
    </svg>
  );
}

function PencilIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      className="h-3.5 w-3.5"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m16.5 4.5 3 3L9 18l-4 1 1-4Z" />
    </svg>
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
      className="h-3.5 w-3.5"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2m2 0-.6 12.2A2 2 0 0 1 14.4 21H9.6a2 2 0 0 1-2-1.8L7 7h10Z"
      />
    </svg>
  );
}
