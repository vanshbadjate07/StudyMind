import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  generateNotebookPresentation,
  getNotebookPresentation,
  type PresentationGenerateOptions,
  type PresentationRecord,
} from "../lib/api";

const POLL_INTERVAL_MS = 2000;

function isInFlight(presentation: PresentationRecord | null): boolean {
  return (
    presentation !== null &&
    (presentation.status === "pending" || presentation.status === "generating")
  );
}

/** Same shape as useQuiz (user-triggered generation, poll until it settles),
 * with a slower tick: a deck is several LLM calls plus a render pass, so it
 * takes noticeably longer than a quiz and there's nothing to gain from
 * asking every 1.5s. */
export function usePresentation(notebookId: string) {
  const [presentation, setPresentation] = useState<PresentationRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const presentationRef = useRef<PresentationRecord | null>(null);
  const errorRef = useRef<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Bumped on every notebookId change so an in-flight fetch from a
  // superseded cycle can't clobber state after a newer cycle already started.
  const requestIdRef = useRef(0);

  const fetchOnce = useCallback(async (id: string, requestId: number) => {
    try {
      const record = await getNotebookPresentation(id);
      if (requestId !== requestIdRef.current) return;
      presentationRef.current = record;
      errorRef.current = null;
      setPresentation(record);
      setError(null);
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const message = err instanceof ApiError ? err.message : "Couldn't load the slides.";
      errorRef.current = message;
      setError(message);
    } finally {
      if (requestId === requestIdRef.current) setIsLoading(false);
    }
  }, []);

  const scheduleNextPoll = useCallback(
    (id: string, requestId: number) => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      if (errorRef.current || !isInFlight(presentationRef.current)) return;
      timeoutRef.current = setTimeout(() => {
        void (async () => {
          await fetchOnce(id, requestId);
          if (requestId === requestIdRef.current) scheduleNextPoll(id, requestId);
        })();
      }, POLL_INTERVAL_MS);
    },
    [fetchOnce],
  );

  useEffect(() => {
    requestIdRef.current += 1;
    const requestId = requestIdRef.current;
    errorRef.current = null;
    setIsLoading(true);
    setError(null);

    void (async () => {
      await fetchOnce(notebookId, requestId);
      if (requestId === requestIdRef.current) scheduleNextPoll(notebookId, requestId);
    })();

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
      requestIdRef.current += 1;
    };
  }, [notebookId, fetchOnce, scheduleNextPoll]);

  const generate = useCallback(
    async (options: PresentationGenerateOptions) => {
      const id = notebookId;
      const requestId = requestIdRef.current;
      setIsGenerating(true);
      setError(null);
      errorRef.current = null;
      try {
        const record = await generateNotebookPresentation(id, options);
        if (requestId !== requestIdRef.current) return; // superseded by a notebook switch/unmount meanwhile
        presentationRef.current = record;
        setPresentation(record);
        scheduleNextPoll(id, requestId);
      } catch (err) {
        if (requestId !== requestIdRef.current) return;
        const message =
          err instanceof ApiError ? err.message : "Couldn't start generating the slides.";
        errorRef.current = message;
        setError(message);
      } finally {
        if (requestId === requestIdRef.current) setIsGenerating(false);
      }
    },
    [notebookId, scheduleNextPoll],
  );

  return { presentation, isLoading, error, isGenerating, generate };
}
