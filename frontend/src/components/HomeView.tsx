import { useState } from "react";
import type { NotebookRecord } from "../lib/api";
import { ConfirmDialog } from "./ConfirmDialog";
import { NotebookCard } from "./NotebookCard";

interface HomeViewProps {
  notebooks: NotebookRecord[];
  isLoading: boolean;
  error: string | null;
  onCreateNotebook: () => void;
  onOpenNotebook: (id: string) => void;
  onRenameNotebook: (id: string, name: string) => Promise<void>;
  onDeleteNotebook: (id: string) => Promise<void>;
}

export function HomeView({
  notebooks,
  isLoading,
  error,
  onCreateNotebook,
  onOpenNotebook,
  onRenameNotebook,
  onDeleteNotebook,
}: HomeViewProps) {
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  const pendingDeleteNotebook = notebooks.find((n) => n.id === pendingDeleteId) ?? null;

  const confirmDelete = async () => {
    if (!pendingDeleteId) return;
    setIsDeleting(true);
    try {
      await onDeleteNotebook(pendingDeleteId);
      setPendingDeleteId(null);
      setDeleteError(null);
    } catch {
      setDeleteError("Couldn't delete this notebook.");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-6 py-10 lg:px-12">
      <div className="mx-auto w-full max-w-5xl">
        <h1 className="text-xl font-semibold tracking-tight text-ink">Your notebooks</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Each notebook groups the resources you're studying from — open one to chat, or create a new
          one to get started.
        </p>

        {error && (
          <p role="alert" className="mt-6 text-sm text-status-failed">
            {error}
          </p>
        )}
        {deleteError && (
          <p role="alert" className="mt-6 text-sm text-status-failed">
            {deleteError}
          </p>
        )}

        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <button
            type="button"
            onClick={onCreateNotebook}
            className="flex min-h-[168px] flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-line-strong p-4 text-center text-ink-muted transition-colors hover:border-brand hover:text-brand"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-brand-subtle text-brand-ink">
              <PlusIcon />
            </span>
            <span className="text-sm font-medium">New notebook</span>
          </button>

          {isLoading ? (
            <>
              <div className="h-[168px] animate-pulse rounded-xl bg-line/60" />
              <div className="h-[168px] animate-pulse rounded-xl bg-line/60" />
            </>
          ) : (
            notebooks.map((notebook) => (
              <NotebookCard
                key={notebook.id}
                notebook={notebook}
                onOpen={() => onOpenNotebook(notebook.id)}
                onRename={(name) => onRenameNotebook(notebook.id, name)}
                onDeleteClick={() => {
                  setDeleteError(null);
                  setPendingDeleteId(notebook.id);
                }}
              />
            ))
          )}
        </div>
      </div>

      <ConfirmDialog
        open={pendingDeleteNotebook !== null}
        title="Delete this notebook?"
        description={
          pendingDeleteNotebook
            ? `"${pendingDeleteNotebook.name}" and every document inside it will be permanently removed.`
            : ""
        }
        confirmLabel={isDeleting ? "Deleting…" : "Delete"}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDeleteId(null)}
      />
    </div>
  );
}

function PlusIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      className="h-4 w-4"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
    </svg>
  );
}
