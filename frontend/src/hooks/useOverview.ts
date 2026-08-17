import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  getNotebookOverview,
  regenerateNotebookOverview,
  type OverviewRecord,
} from "../lib/api";

const POLL_INTERVAL_MS = 1500;
// Extra poll ticks kept alive after the notebook's document set changes,
// even once the overview already looks "ready" — the backend regenerates
// asynchronously and may not have flipped the row to "generating" yet at
// the instant we notice the change, so without this a regeneration that
// starts a beat late gets missed entirely.
const SETTLE_POLL_ATTEMPTS = 5;

function isInFlight(overview: OverviewRecord | null): boolean {
  return overview === null || overview.status === "pending" || overview.status === "generating";
}

/** `watchKey` should change whenever the notebook's document set changes
 * (a document finished processing, failed, was added, or was removed) —
 * e.g. a signature built from each document's id + status. That's the
 * signal this hook uses to know a regeneration might be starting, since
 * `notebookId` alone never changes when documents are added later.
 *
 * Polling is a self-scheduling loop (recursive setTimeout), not a
 * useEffect-driven setInterval — the stop condition (settled, and out of
 * "settle" retries) is evaluated once per actual poll tick via refs, not by
 * waiting for a React re-render to notice. Relying on re-renders to
 * re-evaluate the stop condition is fragile: React skips re-rendering a
 * state update that's reference-equal to the current value, which would
 * silently leave a stale interval running forever with no way to stop it.
 *
 * `onSettled` fires once whenever a poll cycle observes the overview go
 * from in-flight to settled (ready or failed) — the earliest point a
 * server-side auto-rename from that same generation run (see
 * overview_generation.py's `_maybe_autoname_notebook`, which commits in the
 * same transaction as the overview's READY status) is guaranteed visible.
 * Without this, the notebook's new name only ever showed up after a full
 * page reload, since nothing else re-fetches the notebooks list. */
export function useOverview(notebookId: string, watchKey: string, onSettled?: () => void) {
  const [overview, setOverview] = useState<OverviewRecord | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isRegenerating, setIsRegenerating] = useState(false);

  const overviewRef = useRef<OverviewRecord | null>(null);
  const errorRef = useRef<string | null>(null);
  const settleAttemptsRef = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wasInFlightRef = useRef(false);
  const onSettledRef = useRef(onSettled);
  onSettledRef.current = onSettled;
  // Bumped on every notebookId/watchKey change so an in-flight fetch from a
  // superseded cycle can't clobber state after a newer cycle already started.
  const requestIdRef = useRef(0);

  const fetchOnce = useCallback(async (id: string, requestId: number) => {
    try {
      const record = await getNotebookOverview(id);
      if (requestId !== requestIdRef.current) return;
      const nowInFlight = isInFlight(record);
      if (wasInFlightRef.current && !nowInFlight) onSettledRef.current?.();
      wasInFlightRef.current = nowInFlight;
      overviewRef.current = record;
      errorRef.current = null;
      setOverview(record);
      setError(null);
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const message = err instanceof ApiError ? err.message : "Couldn't load the overview.";
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
      const stillInFlight = isInFlight(overviewRef.current);
      const shouldContinue = !errorRef.current && (stillInFlight || settleAttemptsRef.current > 0);
      if (!shouldContinue) return;
      if (!stillInFlight) settleAttemptsRef.current -= 1;

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
    settleAttemptsRef.current = SETTLE_POLL_ATTEMPTS;
    errorRef.current = null;
    wasInFlightRef.current = false;
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
      // Also invalidates this cycle's requestId on a true unmount (not just
      // a notebookId/watchKey change, which already bumps it via the next
      // effect run) — otherwise a fetch already in flight when the
      // component unmounts would resolve afterward, pass its own staleness
      // check (nothing else would have bumped requestIdRef), and schedule
      // another poll that nothing left mounted could ever cancel.
      requestIdRef.current += 1;
    };
  }, [notebookId, watchKey, fetchOnce, scheduleNextPoll]);

  const regenerate = useCallback(async () => {
    const id = notebookId;
    const requestId = requestIdRef.current;
    setIsRegenerating(true);
    setError(null);
    errorRef.current = null;
    try {
      const record = await regenerateNotebookOverview(id);
      if (requestId !== requestIdRef.current) return; // superseded by a notebook switch/unmount meanwhile
      overviewRef.current = record;
      wasInFlightRef.current = isInFlight(record);
      setOverview(record);
      settleAttemptsRef.current = SETTLE_POLL_ATTEMPTS;
      scheduleNextPoll(id, requestId);
    } catch (err) {
      if (requestId !== requestIdRef.current) return;
      const message = err instanceof ApiError ? err.message : "Couldn't restart the overview.";
      errorRef.current = message;
      setError(message);
    } finally {
      if (requestId === requestIdRef.current) setIsRegenerating(false);
    }
  }, [notebookId, scheduleNextPoll]);

  return { overview, isLoading, error, isRegenerating, regenerate };
}
