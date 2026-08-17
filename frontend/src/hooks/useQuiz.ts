import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, generateNotebookQuiz, getNotebookQuiz, type QuizRecord } from "../lib/api";

const POLL_INTERVAL_MS = 1500;

function isInFlight(quiz: QuizRecord | null): boolean {
  return quiz !== null && (quiz.status === "pending" || quiz.status === "generating");
}

/** Simpler than useOverview: a quiz is never generated automatically (no
 * watchKey-driven regeneration to catch, no auto-rename side effect to
 * surface) — it only ever moves from PENDING/GENERATING to READY/FAILED
 * once, in response to the user's own generate() call. */
export function useQuiz(notebookId: string) {
  const [quiz, setQuiz] = useState<QuizRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const quizRef = useRef<QuizRecord | null>(null);
  const errorRef = useRef<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Bumped on every notebookId change so an in-flight fetch from a
  // superseded cycle can't clobber state after a newer cycle already started.
  const requestIdRef = useRef(0);

  const fetchOnce = useCallback(async (id: string, requestId: number) => {
    try {
      const record = await getNotebookQuiz(id);
      if (requestId !== requestIdRef.current) return;
      quizRef.current = record;
      errorRef.current = null;
      setQuiz(record);
      setError(null);
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const message = err instanceof ApiError ? err.message : "Couldn't load the quiz.";
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
      if (errorRef.current || !isInFlight(quizRef.current)) return;
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

  const generate = useCallback(async () => {
    const id = notebookId;
    const requestId = requestIdRef.current;
    setIsGenerating(true);
    setError(null);
    errorRef.current = null;
    try {
      const record = await generateNotebookQuiz(id);
      if (requestId !== requestIdRef.current) return; // superseded by a notebook switch/unmount meanwhile
      quizRef.current = record;
      setQuiz(record);
      scheduleNextPoll(id, requestId);
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const message = err instanceof ApiError ? err.message : "Couldn't start generating the quiz.";
      errorRef.current = message;
      setError(message);
    } finally {
      if (requestId === requestIdRef.current) setIsGenerating(false);
    }
  }, [notebookId, scheduleNextPoll]);

  return { quiz, isLoading, error, isGenerating, generate };
}
