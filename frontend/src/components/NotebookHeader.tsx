import { useEffect, useRef, useState } from "react";
import type { GoalType, NotebookRecord } from "../lib/api";
import { GoalDialog } from "./GoalDialog";

const GOAL_LABELS: Record<GoalType, string> = {
  exam: "Exam prep",
  interview: "Interview prep",
  skill: "Learning a skill",
  exploration: "Just exploring",
  custom: "Custom goal",
};

interface NotebookHeaderProps {
  notebook: NotebookRecord;
  onSetGoal: (goalType: GoalType, description?: string) => Promise<void>;
  onRename: (name: string) => Promise<void>;
}

export function NotebookHeader({ notebook, onSetGoal, onRename }: NotebookHeaderProps) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [isRenaming, setIsRenaming] = useState(false);
  const [draftName, setDraftName] = useState(notebook.name);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isRenaming) setDraftName(notebook.name);
  }, [notebook.name, isRenaming]);

  const startRenaming = () => {
    setDraftName(notebook.name);
    setIsRenaming(true);
  };

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
    }
  };

  return (
    <div className="mb-8 flex items-start justify-between gap-4">
      <div className="min-w-0">
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
                setIsRenaming(false);
              }
            }}
            aria-label="Notebook name"
            className="w-full max-w-sm rounded-lg border border-brand bg-surface px-2 py-1 text-xl font-semibold tracking-tight text-ink focus:outline-none"
          />
        ) : (
          <button
            type="button"
            onClick={startRenaming}
            className="rounded-lg px-2 py-1 -mx-2 -my-1 text-left text-xl font-semibold tracking-tight text-ink transition-colors hover:bg-paper"
          >
            {notebook.name}
          </button>
        )}
        <div className="mt-2 px-2">
          {notebook.goal_type ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-paper px-2.5 py-1 text-xs font-medium text-ink-muted">
                <GoalIcon />
                {GOAL_LABELS[notebook.goal_type]}
                {notebook.goal_description ? ` · ${notebook.goal_description}` : ""}
              </span>
              <button
                type="button"
                onClick={() => setDialogOpen(true)}
                className="text-xs font-medium text-ink-faint underline decoration-dotted underline-offset-2 hover:text-ink"
              >
                Edit
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setDialogOpen(true)}
              className="inline-flex items-center gap-1.5 rounded-full border border-brand bg-brand-subtle px-3 py-1.5 text-xs font-semibold text-brand-ink transition-colors hover:bg-brand-subtle/70"
            >
              <PlusIcon />
              Set a goal for this notebook
            </button>
          )}
        </div>
      </div>

      <GoalDialog
        open={dialogOpen}
        currentGoalType={notebook.goal_type}
        currentDescription={notebook.goal_description}
        onSave={onSetGoal}
        onClose={() => setDialogOpen(false)}
      />
    </div>
  );
}

function GoalIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      className="h-3 w-3"
    >
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="0.75" fill="currentColor" stroke="none" />
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
      strokeWidth={1.9}
      className="h-3 w-3"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 5v14M5 12h14" />
    </svg>
  );
}
