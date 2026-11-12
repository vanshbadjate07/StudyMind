import { useState, type ReactNode } from "react";
import type { NotebookRecord } from "../lib/api";
import { GOAL_LABELS } from "../lib/goalLabels";
import { InfoDialog } from "./InfoDialog";
import { PrivacyContent, TermsContent } from "./LegalContent";

export type WorkspaceSection = "documents" | "chat" | "quiz" | "slides";

interface NavItem {
  section: WorkspaceSection | "interview";
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
  activeNotebook: NotebookRecord | null;
  activeSection: WorkspaceSection;
  onSelectSection: (section: WorkspaceSection) => void;
  onGoHome: () => void;
}

export function Sidebar({ activeNotebook, activeSection, onSelectSection, onGoHome }: SidebarProps) {
  const [openDialog, setOpenDialog] = useState<"terms" | "privacy" | null>(null);

  return (
    <aside className="hidden w-60 shrink-0 border-r border-line bg-surface lg:flex lg:flex-col">
      <button
        type="button"
        onClick={onGoHome}
        className="flex items-center gap-2.5 border-b border-line px-5 py-4 text-left transition-colors hover:bg-paper"
      >
        <Logo />
        <div>
          <p className="text-sm font-semibold tracking-tight text-ink">StudyMind</p>
          <p className="text-[11px] text-ink-muted">Your material, understood.</p>
        </div>
      </button>

      {activeNotebook && (
        <div className="border-b border-line p-3">
          <button
            type="button"
            onClick={onGoHome}
            className="inline-flex items-center gap-1 text-[11px] font-medium text-ink-faint transition-colors hover:text-ink"
          >
            <BackIcon />
            All notebooks
          </button>
          <p className="mt-2 truncate px-0.5 text-sm font-semibold text-ink" title={activeNotebook.name}>
            {activeNotebook.name}
          </p>
          {activeNotebook.goal_type && (
            <p className="mt-0.5 truncate px-0.5 text-[11px] text-ink-muted">
              {GOAL_LABELS[activeNotebook.goal_type]}
            </p>
          )}
        </div>
      )}

      {activeNotebook && (
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
                isActive
                  ? "bg-brand-subtle text-brand-ink"
                  : "text-ink-muted hover:bg-paper hover:text-ink"
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
      )}

      <div className={`border-t border-line p-3 ${activeNotebook ? "" : "mt-auto"}`}>
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

function BackIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      className="h-3 w-3"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M15 18l-6-6 6-6" />
    </svg>
  );
}
