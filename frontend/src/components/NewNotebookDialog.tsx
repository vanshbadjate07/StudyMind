import { useEffect, useRef, useState } from "react";

interface NewNotebookDialogProps {
  open: boolean;
  onCreate: (name: string) => Promise<void>;
  onClose: () => void;
}

export function NewNotebookDialog({ open, onCreate, onClose }: NewNotebookDialogProps) {
  const [name, setName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setName("");
      dialog.showModal();
      inputRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const handleCreate = async () => {
    setIsCreating(true);
    try {
      await onCreate(name.trim() || "Untitled Notebook");
      onClose();
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      className="fixed inset-0 m-auto w-full max-w-sm rounded-xl border border-line p-0 shadow-lg backdrop:bg-ink/40"
    >
      <form
        className="p-5"
        onSubmit={(event) => {
          event.preventDefault();
          void handleCreate();
        }}
      >
        <h2 className="text-base font-semibold text-ink">New notebook</h2>
        <p className="mt-1 text-xs text-ink-muted">
          A notebook groups the resources you're studying from — add several documents for one
          subject.
        </p>
        <label htmlFor="notebook-name" className="sr-only">
          Notebook name
        </label>
        <input
          ref={inputRef}
          id="notebook-name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Learning Python"
          className="mt-4 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
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
            type="submit"
            disabled={isCreating}
            className="rounded-lg bg-brand px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-hover disabled:opacity-50"
          >
            {isCreating ? "Creating…" : "Create"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
