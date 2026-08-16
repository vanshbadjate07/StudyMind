import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  getOverview,
  regenerateOverview,
  type OverviewRecord,
} from "../lib/api";

const POLL_INTERVAL_MS = 1500;

function isInFlight(overview: OverviewRecord | null): boolean {
  return overview === null || overview.status === "pending" || overview.status === "generating";
}

export function useOverview(documentId: string) {
  const [overview, setOverview] = useState<OverviewRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const record = await getOverview(documentId);
      setOverview(record);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load the overview.");
    } finally {
      setIsLoading(false);
    }
  }, [documentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const stopPolling = () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };

    if (isInFlight(overview) && !error && intervalRef.current === null) {
      intervalRef.current = setInterval(() => {
        void refresh();
      }, POLL_INTERVAL_MS);
    } else if (!isInFlight(overview) || error) {
      stopPolling();
    }

    return stopPolling;
  }, [overview, error, refresh]);

  const regenerate = useCallback(async () => {
    setIsRegenerating(true);
    setError(null);
    try {
      const record = await regenerateOverview(documentId);
      setOverview(record);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't restart the overview.");
    } finally {
      setIsRegenerating(false);
    }
  }, [documentId]);

  return { overview, isLoading, error, isRegenerating, regenerate };
}
