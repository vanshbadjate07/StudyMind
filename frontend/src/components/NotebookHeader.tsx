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
        {notebook.goal_type ? (
          <p className="mt-1 px-2 text-sm text-ink-muted">
            Goal: {GOAL_LABELS[notebook.goal_type]}
            {notebook.goal_description ? ` · ${notebook.goal_description}` : ""}
          </p>
        ) : (
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="mt-1 px-2 text-sm font-medium text-brand hover:text-brand-hover"
          >
            Set a goal for this notebook
          </button>
        )}
      </div>
      {notebook.goal_type && (
        <button
          type="button"
          onClick={() => setDialogOpen(true)}
          className="shrink-0 text-xs font-medium text-ink-muted hover:text-ink"
        >
          Edit goal
        </button>
      )}

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
