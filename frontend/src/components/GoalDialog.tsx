import { useEffect, useRef, useState } from "react";
import type { GoalType } from "../lib/api";

const GOAL_PRESETS: { type: GoalType; label: string; description: string }[] = [
  { type: "exam", label: "Exam prep", description: "Studying for a test or exam." },
  { type: "interview", label: "Interview prep", description: "Preparing for a job interview." },
  { type: "skill", label: "Learning a skill", description: "Picking up something new." },
  { type: "exploration", label: "Just exploring", description: "No specific goal yet." },
];

interface GoalDialogProps {
  open: boolean;
  currentGoalType: GoalType | null;
  currentDescription: string | null;
  onSave: (goalType: GoalType, description?: string) => Promise<void>;
  onClose: () => void;
}

export function GoalDialog({
  open,
  currentGoalType,
  currentDescription,
  onSave,
  onClose,
}: GoalDialogProps) {
  const [selected, setSelected] = useState<GoalType | null>(currentGoalType);
  const [description, setDescription] = useState(currentDescription ?? "");
  const [isSaving, setIsSaving] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setSelected(currentGoalType);
      setDescription(currentDescription ?? "");
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open, currentGoalType, currentDescription]);

  const handleSave = async () => {
    if (!selected) return;
    setIsSaving(true);
    try {
      await onSave(selected, description.trim() || undefined);
      onClose();
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className="fixed inset-0 m-auto w-full max-w-md rounded-xl border border-line p-0 shadow-lg backdrop:bg-ink/40"
    >
      <div className="p-5">
        <h2 className="text-base font-semibold text-ink">What are you here to do?</h2>
        <p className="mt-1 text-xs text-ink-muted">
          This shapes how chat, quizzes, and interviews behave for this notebook.
        </p>

        <div className="mt-4 grid grid-cols-2 gap-2">
          {GOAL_PRESETS.map((preset) => (
            <button
              key={preset.type}
              type="button"
              onClick={() => setSelected(preset.type)}
              className={`rounded-lg border p-3 text-left transition-colors ${
                selected === preset.type
                  ? "border-brand bg-brand-subtle"
                  : "border-line hover:bg-paper"
              }`}
            >
              <p className="text-sm font-medium text-ink">{preset.label}</p>
              <p className="mt-0.5 text-xs text-ink-muted">{preset.description}</p>
            </button>
          ))}
        </div>

        <label className="mt-4 block text-xs font-medium text-ink-muted" htmlFor="goal-description">
          Or describe it in your own words
        </label>
        <textarea
          id="goal-description"
          value={description}
          onChange={(event) => {
            setDescription(event.target.value);
            setSelected("custom");
          }}
          rows={2}
          placeholder="e.g. Preparing for a MongoDB certification exam"
          className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
        />

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-sm font-medium text-ink-muted hover:bg-paper"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!selected || isSaving}
            className="rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-hover disabled:opacity-50"
          >
            {isSaving ? "Saving…" : "Save goal"}
          </button>
        </div>
      </div>
    </dialog>
  );
}
