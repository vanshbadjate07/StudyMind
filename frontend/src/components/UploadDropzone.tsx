import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { ApiError, uploadDocument, type DocumentRecord } from "../lib/api";
import { validateFile } from "../lib/validation";

interface UploadDropzoneProps {
  notebookId: string;
  onUploaded: (document: DocumentRecord) => void;
}

interface UploadItem {
  id: string;
  file: File;
  progress: number;
  status: "queued" | "uploading" | "error";
  error?: string;
}

export function UploadDropzone({ notebookId, onUploaded }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [items, setItems] = useState<UploadItem[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const isBusy = items.some((item) => item.status === "queued" || item.status === "uploading");

  const updateItem = (id: string, patch: Partial<UploadItem>) => {
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, ...patch } : item)));
  };

  const uploadOne = async (item: UploadItem) => {
    const validation = validateFile(item.file);
    if (!validation.valid) {
      updateItem(item.id, { status: "error", error: validation.reason ?? "This file can't be uploaded." });
      return;
    }

    updateItem(item.id, { status: "uploading" });
    try {
      const document = await uploadDocument(notebookId, item.file, (percent) => {
        updateItem(item.id, { progress: percent });
      });
      onUploaded(document);
      setItems((prev) => prev.filter((existing) => existing.id !== item.id));
    } catch (err) {
      updateItem(item.id, {
        status: "error",
        error: err instanceof ApiError ? err.message : "Upload failed. Please try again.",
      });
    }
  };

  const handleFiles = async (files: File[]) => {
    if (files.length === 0) return;
    const newItems: UploadItem[] = files.map((file) => ({
      id: crypto.randomUUID(),
      file,
      progress: 0,
      status: "queued",
    }));
    setItems((prev) => [...prev, ...newItems]);
    for (const item of newItems) {
      await uploadOne(item);
    }
  };

  const dismissItem = (id: string) => {
    setItems((prev) => prev.filter((item) => item.id !== id));
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    void handleFiles(Array.from(event.dataTransfer.files));
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    void handleFiles(Array.from(event.target.files ?? []));
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={`rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          isDragging ? "border-brand bg-brand-subtle" : "border-line-strong bg-surface"
        }`}
      >
        <label htmlFor="document-upload" className="flex cursor-pointer flex-col items-center gap-3">
          <input
            ref={inputRef}
            id="document-upload"
            type="file"
            accept=".pdf,.docx,.pptx,.txt,.md"
            multiple
            aria-label="Upload a document"
            className="sr-only"
            onChange={handleChange}
            disabled={isBusy}
          />
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-subtle">
            <UploadIcon />
          </span>
          <div>
            <p className="text-sm font-medium text-ink">
              <span className="text-brand">Click to upload</span> or drag and drop
            </p>
            <p className="mt-1 text-xs text-ink-muted">
              PDF, Word, PowerPoint, or text, up to 50MB — select multiple to upload at once
            </p>
          </div>
        </label>
      </div>

      {items.length > 0 && (
        <ul className="mt-4 space-y-2">
          {items.map((item) => (
            <li key={item.id} className="rounded-lg border border-line bg-surface p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="truncate text-xs text-ink-muted">{item.file.name}</p>
                {item.status === "error" && (
                  <button
                    type="button"
                    onClick={() => dismissItem(item.id)}
                    className="shrink-0 text-xs text-ink-muted hover:text-ink"
                    aria-label={`Dismiss error for ${item.file.name}`}
                  >
                    Dismiss
                  </button>
                )}
              </div>

              {item.status === "error" ? (
                <p role="alert" className="mt-1 text-sm text-status-failed">
                  {item.error}
                </p>
              ) : (
                <div
                  role="progressbar"
                  aria-valuenow={item.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={`Uploading ${item.file.name}`}
                  className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-line"
                >
                  <div
                    className="h-full rounded-full bg-brand transition-[width] duration-150"
                    style={{ width: `${item.progress}%` }}
                  />
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function UploadIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      className="h-6 w-6 text-brand-ink"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 16V4m0 0 4 4m-4-4-4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"
      />
    </svg>
  );
}
