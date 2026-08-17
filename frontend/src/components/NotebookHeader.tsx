import { useState } from "react";
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
}

export function NotebookHeader({ notebook, onSetGoal }: NotebookHeaderProps) {
  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <div className="mb-8 flex items-start justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{notebook.name}</h1>
        {notebook.goal_type ? (
          <p className="mt-1 text-sm text-ink-muted">
            Goal: {GOAL_LABELS[notebook.goal_type]}
            {notebook.goal_description ? ` · ${notebook.goal_description}` : ""}
          </p>
        ) : (
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="mt-1 text-sm font-medium text-brand hover:text-brand-hover"
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
