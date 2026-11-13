import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  continueInterview as continueInterviewRequest,
  endInterview as endInterviewRequest,
  getNotebookInterview,
  startNotebookInterview,
  submitInterviewAnswer,
  type InterviewSessionRecord,
  type InterviewStartOptions,
} from "../lib/api";

/** Unlike useQuiz / usePresentation / useOverview, this hook does NOT poll.
 * Those features hand work to a background task and watch a status row
 * settle; an interview turn is synchronous - the request returns the scored
 * answer and the next question together - so there is nothing to poll for.
 * The stale-response guard is still here, because switching notebooks
 * mid-request is just as possible as it is for the polling hooks. */
export function useInterview(notebookId: string) {
  const [session, setSession] = useState<InterviewSessionRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isEnding, setIsEnding] = useState(false);

  // Bumped on every notebookId change and on unmount, so a reply from a
  // superseded request can't overwrite state belonging to a notebook the
  // user has already switched to.
  const requestIdRef = useRef(0);

  useEffect(() => {
    requestIdRef.current += 1;
    const requestId = requestIdRef.current;
    setIsLoading(true);
    setError(null);
    setSession(null);

    void (async () => {
      try {
        const record = await getNotebookInterview(notebookId);
        if (requestId !== requestIdRef.current) return;
        setSession(record);
      } catch (err) {
        if (requestId !== requestIdRef.current) return;
        setError(err instanceof ApiError ? err.message : "Couldn't load the interview.");
      } finally {
        if (requestId === requestIdRef.current) setIsLoading(false);
      }
    })();

    return () => {
      requestIdRef.current += 1;
    };
  }, [notebookId]);

  /** Shared wrapper for the four mutating calls: they differ only in which
   * busy flag they raise and what their failure message says. */
  const run = useCallback(
    async (
      action: () => Promise<InterviewSessionRecord>,
      setBusy: (busy: boolean) => void,
      fallbackMessage: string,
    ) => {
      const requestId = requestIdRef.current;
      setBusy(true);
      setError(null);
      try {
        const record = await action();
        if (requestId !== requestIdRef.current) return;
        setSession(record);
      } catch (err) {
        if (requestId !== requestIdRef.current) return;
        setError(err instanceof ApiError ? err.message : fallbackMessage);
      } finally {
        if (requestId === requestIdRef.current) setBusy(false);
      }
    },
    [],
  );

  const start = useCallback(
    (options: InterviewStartOptions) =>
      run(
        () => startNotebookInterview(notebookId, options),
        setIsStarting,
        "Couldn't start the interview.",
      ),
    [notebookId, run],
  );

  const submitAnswer = useCallback(
    (answer: string) => {
      if (session === null) return Promise.resolve();
      const interviewId = session.id;
      return run(
        () => submitInterviewAnswer(interviewId, answer),
        setIsSubmitting,
        "Couldn't submit your answer.",
      );
    },
    [session, run],
  );

  const resume = useCallback(() => {
    if (session === null) return Promise.resolve();
    const interviewId = session.id;
    return run(
      () => continueInterviewRequest(interviewId),
      setIsSubmitting,
      "Couldn't get the next question.",
    );
  }, [session, run]);

  const end = useCallback(() => {
    if (session === null) return Promise.resolve();
    const interviewId = session.id;
    return run(() => endInterviewRequest(interviewId), setIsEnding, "Couldn't end the interview.");
  }, [session, run]);

  /** Clears the finished interview from view so the setup form shows again.
   * Local only: the completed session stays on the server as a record of the
   * run, it just isn't what this screen is showing any more. */
  const dismissReport = useCallback(() => {
    setSession(null);
    setError(null);
  }, []);

  return {
    session,
    isLoading,
    error,
    isStarting,
    isSubmitting,
    isEnding,
    start,
    submitAnswer,
    resume,
    end,
    dismissReport,
  };
}
