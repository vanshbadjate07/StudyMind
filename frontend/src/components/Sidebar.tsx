import { useEffect, useRef, useState, type ReactNode } from "react";
import type { NotebookRecord } from "../lib/api";
import { ConfirmDialog } from "./ConfirmDialog";
import { InfoDialog } from "./InfoDialog";
import { PrivacyContent, TermsContent } from "./LegalContent";

export type WorkspaceSection = "documents" | "chat";

interface NavItem {
  section: WorkspaceSection | "quiz" | "slides" | "interview";
  label: string;
  icon: ReactNode;
  soon?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    section: "documents",
    label: "Documents",
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z M14 3v5h5"
      />
    ),
  },
  {
    section: "chat",
    label: "Chat",
    icon: <path strokeLinecap="round" strokeLinejoin="round" d="M4 5h16v10H8l-4 4V5Z" />,
  },
  {
    section: "quiz",
    label: "Quiz",
    soon: true,
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9 10a3 3 0 1 1 4 2.8c-.6.3-1 .9-1 1.6v.4M12 17.5h.01M5 5h14v14H5V5Z"
      />
    ),
  },
  {
    section: "slides",
    label: "Slides",
    soon: true,
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4 5h16v11H4V5Zm4 15h8M12 16v4"
      />
    ),
  },
  {
    section: "interview",
    label: "Interview",
    soon: true,
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3ZM6 11a6 6 0 0 0 12 0M12 17v4m-3 0h6"
      />
    ),
  },
];

interface SidebarProps {
  notebooks: NotebookRecord[];
  activeNotebookId: string | null;
  notebooksLoading: boolean;
  activeSection: WorkspaceSection;
  onSelectSection: (section: WorkspaceSection) => void;
  onSelectNotebook: (id: string) => void;
  onCreateNotebook: () => void;
  onDeleteNotebook: (id: string) => Promise<void>;
  onRenameNotebook: (id: string, name: string) => Promise<void>;
}

export function Sidebar({
  notebooks,
  activeNotebookId,
  notebooksLoading,
  activeSection,
  onSelectSection,
  onSelectNotebook,
  onCreateNotebook,
  onDeleteNotebook,
  onRenameNotebook,
}: SidebarProps) {
  const [openDialog, setOpenDialog] = useState<"terms" | "privacy" | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draftName, setDraftName] = useState("");
  const renameInputRef = useRef<HTMLInputElement>(null);

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

  useEffect(() => {
    if (renamingId) {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    }
  }, [renamingId]);

  const startRenaming = (notebook: NotebookRecord) => {
    setDraftName(notebook.name);
    setRenamingId(notebook.id);
  };

  const commitRename = async (notebook: NotebookRecord) => {
    const trimmed = draftName.trim();
    setRenamingId(null);
    if (trimmed && trimmed !== notebook.name) {
      await onRenameNotebook(notebook.id, trimmed);
    }
  };

  return (
    <aside className="hidden w-60 shrink-0 border-r border-line bg-surface lg:flex lg:flex-col">
      <div className="flex items-center gap-2.5 border-b border-line px-5 py-4">
        <Logo />
        <div>
          <p className="text-sm font-semibold tracking-tight text-ink">StudyMind</p>
          <p className="text-[11px] text-ink-muted">Your material, understood.</p>
        </div>
      </div>

      <div className="border-b border-line p-3">
        <div className="flex items-center justify-between px-2 pt-1 pb-2">
          <p className="text-[11px] font-semibold tracking-wider text-ink-faint uppercase">
            Notebooks
          </p>
          <button
            type="button"
            onClick={onCreateNotebook}
            aria-label="New notebook"
            className="rounded p-1 text-ink-faint transition-colors hover:bg-paper hover:text-ink"
          >
            <PlusIcon />
          </button>
        </div>
        {notebooksLoading ? (
          <div className="space-y-1.5 px-2">
            <div className="h-7 animate-pulse rounded-lg bg-line/60" />
            <div className="h-7 animate-pulse rounded-lg bg-line/60" />
          </div>
        ) : notebooks.length === 0 ? (
          <p className="px-2 text-xs text-ink-muted">No notebooks yet.</p>
        ) : (
          <ul className="max-h-40 space-y-0.5 overflow-y-auto">
            {notebooks.map((notebook) =>
              renamingId === notebook.id ? (
                <li key={notebook.id} className="flex items-center px-1">
                  <input
                    ref={renameInputRef}
                    value={draftName}
                    onChange={(event) => setDraftName(event.target.value)}
                    onBlur={() => void commitRename(notebook)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        void commitRename(notebook);
                      } else if (event.key === "Escape") {
                        event.preventDefault();
                        setRenamingId(null);
                      }
                    }}
                    aria-label="Notebook name"
                    className="min-w-0 flex-1 rounded-lg border border-brand bg-paper px-3 py-1.5 text-sm font-medium text-ink focus:outline-none"
                  />
                </li>
              ) : (
                <li key={notebook.id} className="group flex items-center">
                  <button
                    type="button"
                    onClick={() => onSelectNotebook(notebook.id)}
                    onDoubleClick={() => startRenaming(notebook)}
                    aria-current={notebook.id === activeNotebookId ? "true" : undefined}
                    title="Double-click to rename"
                    className={`block min-w-0 flex-1 truncate rounded-lg px-3 py-1.5 text-left text-sm font-medium transition-colors ${
                      notebook.id === activeNotebookId
                        ? "bg-brand-subtle text-brand-ink"
                        : "text-ink-muted hover:bg-paper hover:text-ink"
                    }`}
                  >
                    {notebook.name}
                  </button>
                  <button
                    type="button"
                    onClick={() => startRenaming(notebook)}
                    aria-label={`Rename ${notebook.name}`}
                    className="shrink-0 rounded-lg p-1.5 text-ink-faint opacity-0 transition-colors hover:bg-paper hover:text-ink group-hover:opacity-100 focus-visible:opacity-100"
                  >
                    <PencilIcon />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDeleteError(null);
                      setPendingDeleteId(notebook.id);
                    }}
                    aria-label={`Delete ${notebook.name}`}
                    className="shrink-0 rounded-lg p-1.5 text-ink-faint opacity-0 transition-colors hover:bg-paper hover:text-status-failed group-hover:opacity-100 focus-visible:opacity-100"
                  >
                    <TrashIcon />
                  </button>
                </li>
              ),
            )}
          </ul>
        )}
        {deleteError && (
          <p role="alert" className="mt-2 px-2 text-xs text-status-failed">
            {deleteError}
          </p>
        )}
      </div>

      <nav aria-label="Workspace sections" className="flex-1 p-3">
        <p className="px-2 pt-2 pb-1 text-[11px] font-semibold tracking-wider text-ink-faint uppercase">
          Workspace
        </p>
        <ul className="space-y-1">
          {NAV_ITEMS.map((item) => {
            const isActive = !item.soon && item.section === activeSection;
            const content = (
              <>
                <span className="flex items-center gap-2.5">
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={1.6}
                    className="h-4 w-4"
                  >
                    {item.icon}
                  </svg>
                  {item.label}
                </span>
                {item.soon && (
                  <span className="rounded-full bg-line px-1.5 py-0.5 text-[10px] font-medium text-ink-faint">
                    Soon
                  </span>
                )}
              </>
            );
            const className = `flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              isActive ? "bg-brand-subtle text-brand-ink" : "text-ink-muted hover:bg-paper hover:text-ink"
            }`;
            return (
              <li key={item.label}>
                {item.soon ? (
                  <div className={className}>{content}</div>
                ) : (
                  <button
                    type="button"
                    onClick={() => onSelectSection(item.section as WorkspaceSection)}
                    aria-current={isActive ? "page" : undefined}
                    className={className}
                  >
                    {content}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t border-line p-3">
        <div className="flex items-center gap-2.5 rounded-lg px-2 py-2 transition-colors hover:bg-paper">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-subtle text-xs font-semibold text-brand-ink">
            L
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-medium text-ink">Local workspace</p>
            <p className="truncate text-[11px] text-ink-muted">Profile & settings</p>
          </div>
          <span className="shrink-0 rounded-full bg-line px-1.5 py-0.5 text-[10px] font-medium text-ink-faint">
            Soon
          </span>
        </div>
        <div className="mt-2 flex gap-3 px-2 text-[11px] text-ink-faint">
          <button type="button" onClick={() => setOpenDialog("terms")} className="hover:text-ink-muted">
            Terms
          </button>
          <button type="button" onClick={() => setOpenDialog("privacy")} className="hover:text-ink-muted">
            Privacy
          </button>
        </div>
      </div>

      <InfoDialog open={openDialog === "terms"} title="Terms of Service" onClose={() => setOpenDialog(null)}>
        <TermsContent />
      </InfoDialog>
      <InfoDialog open={openDialog === "privacy"} title="Privacy Policy" onClose={() => setOpenDialog(null)}>
        <PrivacyContent />
      </InfoDialog>

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
    </aside>
  );
}

function Logo() {
  return (
    <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#C2660B" />
      <path
        d="M9 22V10.5C9 9.67 9.67 9 10.5 9H16v14H10.5A1.5 1.5 0 0 1 9 21.5V22Z"
        fill="#FAF8F5"
        fillOpacity="0.92"
      />
      <path d="M16 9h5.5c.83 0 1.5.67 1.5 1.5V22h-7V9Z" fill="#FAF8F5" fillOpacity="0.6" />
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
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="m16.5 4.5 3 3L9 18l-4 1 1-4Z"
      />
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
