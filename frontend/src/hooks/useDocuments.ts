import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, listNotebookDocuments, type DocumentRecord } from "../lib/api";

const POLL_INTERVAL_MS = 2000;

function hasInFlightDocument(documents: DocumentRecord[]): boolean {
  return documents.some((doc) => doc.status === "pending" || doc.status === "processing");
}

export function useDocuments(notebookId: string | null) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (notebookId === null) {
      setDocuments([]);
      setIsLoading(false);
      return;
    }
    try {
      const fetched = await listNotebookDocuments(notebookId);
      setDocuments(fetched);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't reach the server.");
    } finally {
      setIsLoading(false);
    }
  }, [notebookId]);

  useEffect(() => {
    setIsLoading(true);
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const stopPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    if (hasInFlightDocument(documents) && intervalRef.current === null) {
      intervalRef.current = setInterval(() => {
        void refresh();
      }, POLL_INTERVAL_MS);
    } else if (!hasInFlightDocument(documents)) {
      stopPolling();
    }

    return stopPolling;
  }, [documents, refresh]);

  const addDocument = useCallback((document: DocumentRecord) => {
    setDocuments((prev) => [document, ...prev]);
  }, []);

  const removeDocument = useCallback((documentId: string) => {
    setDocuments((prev) => prev.filter((doc) => doc.id !== documentId));
  }, []);

  return { documents, isLoading, error, addDocument, removeDocument, refresh };
}
