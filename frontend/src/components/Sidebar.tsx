import { useState, type ReactNode } from "react";
import type { NotebookRecord } from "../lib/api";
import { InfoDialog } from "./InfoDialog";
import { PrivacyContent, TermsContent } from "./LegalContent";

interface NavItem {
  label: string;
  icon: ReactNode;
  active?: boolean;
  soon?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Documents",
    active: true,
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z M14 3v5h5"
      />
    ),
  },
  {
    label: "Chat",
    soon: true,
    icon: <path strokeLinecap="round" strokeLinejoin="round" d="M4 5h16v10H8l-4 4V5Z" />,
  },
  {
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
  onSelectNotebook: (id: string) => void;
  onCreateNotebook: () => void;
}

export function Sidebar({
  notebooks,
  activeNotebookId,
  notebooksLoading,
  onSelectNotebook,
  onCreateNotebook,
}: SidebarProps) {
  const [openDialog, setOpenDialog] = useState<"terms" | "privacy" | null>(null);

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
            {notebooks.map((notebook) => (
              <li key={notebook.id}>
                <button
                  type="button"
                  onClick={() => onSelectNotebook(notebook.id)}
                  aria-current={notebook.id === activeNotebookId ? "true" : undefined}
                  className={`block w-full truncate rounded-lg px-3 py-1.5 text-left text-sm font-medium transition-colors ${
                    notebook.id === activeNotebookId
                      ? "bg-brand-subtle text-brand-ink"
                      : "text-ink-muted hover:bg-paper hover:text-ink"
                  }`}
                >
                  {notebook.name}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <nav aria-label="Workspace sections" className="flex-1 p-3">
        <p className="px-2 pt-2 pb-1 text-[11px] font-semibold tracking-wider text-ink-faint uppercase">
          Workspace
        </p>
        <ul className="space-y-1">
          {NAV_ITEMS.map((item) => (
            <li key={item.label}>
              <div
                aria-current={item.active ? "page" : undefined}
                className={`flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                  item.active
                    ? "bg-brand-subtle text-brand-ink"
                    : "text-ink-muted hover:bg-paper hover:text-ink"
                }`}
              >
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
              </div>
            </li>
          ))}
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
