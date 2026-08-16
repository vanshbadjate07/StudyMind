import { useRef, useState, type ChangeEvent, type DragEvent } from "react";
import { ApiError, uploadDocument, type DocumentRecord } from "../lib/api";
import { validateFile } from "../lib/validation";

interface UploadDropzoneProps {
  onUploaded: (document: DocumentRecord) => void;
}

export function UploadDropzone({ onUploaded }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploadingName, setUploadingName] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    setError(null);
    const validation = validateFile(file);
    if (!validation.valid) {
      setError(validation.reason ?? "This file can't be uploaded.");
      return;
    }

    setUploadingName(file.name);
    setProgress(0);
    try {
      const document = await uploadDocument(file, setProgress);
      onUploaded(document);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Upload failed. Please try again.");
    } finally {
      setUploadingName(null);
      setProgress(0);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files[0];
    if (file) void handleFile(file);
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) void handleFile(file);
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
            accept=".pdf"
            aria-label="Upload PDF document"
            className="sr-only"
            onChange={handleChange}
            disabled={uploadingName !== null}
          />
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-brand-subtle">
            <UploadIcon />
          </span>
          <div>
            <p className="text-sm font-medium text-ink">
              <span className="text-brand">Click to upload</span> or drag and drop
            </p>
            <p className="mt-1 text-xs text-ink-muted">PDF, up to 50MB</p>
          </div>
        </label>

        {uploadingName && (
          <div className="mt-6" aria-live="polite">
            <p className="mb-2 truncate text-xs text-ink-muted">Uploading {uploadingName}…</p>
            <div
              role="progressbar"
              aria-valuenow={progress}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`Uploading ${uploadingName}`}
              className="h-1.5 w-full overflow-hidden rounded-full bg-line"
            >
              <div
                className="h-full rounded-full bg-brand transition-[width] duration-150"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-3 text-sm text-status-failed">
          {error}
        </p>
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
