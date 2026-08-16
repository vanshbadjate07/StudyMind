export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentRecord {
  id: string;
  filename: string;
  status: DocumentStatus;
  page_count: number | null;
  char_count: number | null;
  chunk_count: number | null;
  error_reason: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
}

export type OverviewStatus = "pending" | "generating" | "ready" | "failed";

export interface TopicSummary {
  title: string;
  summary: string;
  key_concepts: string[];
}

export interface OverviewRecord {
  id: string;
  document_id: string;
  status: OverviewStatus;
  topics: TopicSummary[];
  estimated_minutes: number | null;
  error_reason: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Response body wasn't JSON; fall back to statusText.
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function listDocuments(): Promise<DocumentRecord[]> {
  const response = await fetch(`${API_BASE_URL}/documents`);
  const data = await handleResponse<{ documents: DocumentRecord[] }>(response);
  return data.documents;
}

export async function getDocument(id: string): Promise<DocumentRecord> {
  const response = await fetch(`${API_BASE_URL}/documents/${id}`);
  return handleResponse<DocumentRecord>(response);
}

export async function deleteDocument(id: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/documents/${id}`, { method: "DELETE" });
  await handleResponse<void>(response);
}

/** Returns null if the overview hasn't started yet (e.g. document isn't ready) — the
 * backend returns 404 for that case, which isn't an error here, just a "not yet" state. */
export async function getOverview(documentId: string): Promise<OverviewRecord | null> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/overview`);
  if (response.status === 404) {
    return null;
  }
  return handleResponse<OverviewRecord>(response);
}

export async function regenerateOverview(documentId: string): Promise<OverviewRecord> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/overview/regenerate`, {
    method: "POST",
  });
  return handleResponse<OverviewRecord>(response);
}

/** Uses XMLHttpRequest instead of fetch so we can report upload progress —
 * fetch has no cross-browser-reliable way to observe request body progress. */
export function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<DocumentRecord> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/documents`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as DocumentRecord);
        return;
      }

      const detail =
        body && typeof body === "object" && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : xhr.statusText || "Upload failed";
      reject(new ApiError(xhr.status, detail));
    };

    xhr.onerror = () => reject(new ApiError(0, "Network error. Is the server running?"));

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}
