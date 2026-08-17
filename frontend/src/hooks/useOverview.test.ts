import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { useOverview } from "./useOverview";

function makeOverview(overrides: Partial<api.OverviewRecord> = {}): api.OverviewRecord {
  return {
    id: "ov-1",
    notebook_id: "nb-1",
    status: "ready",
    short_summary: "Old summary.",
    topics: [{ title: "Old Topic", summary: "s", key_concepts: [] }],
    estimated_minutes: 10,
    error_reason: null,
    error_detail: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("useOverview", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("picks up a regeneration triggered by a new document even after the overview already looked settled", async () => {
    // Regression test: uploading a second document after the first one's
    // overview already finished used to leave the UI stuck showing the
    // stale single-document overview forever, because polling stopped once
    // the overview first settled and nothing restarted it.
    const getSpy = vi
      .spyOn(api, "getNotebookOverview")
      .mockResolvedValueOnce(makeOverview()) // initial load: settled on doc 1 alone
      .mockResolvedValueOnce(makeOverview()) // watchKey changed (doc 2 became ready), backend hasn't started regenerating yet
      .mockResolvedValueOnce(makeOverview({ status: "generating" })) // backend picked it up
      .mockResolvedValue(
        makeOverview({ topics: [{ title: "New Combined Topic", summary: "s", key_concepts: [] }] }),
      ); // regeneration finished

    const { result, rerender } = renderHook(({ watchKey }) => useOverview("nb-1", watchKey), {
      initialProps: { watchKey: "doc-1:ready" },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.overview?.topics[0]?.title).toBe("Old Topic");
    expect(getSpy).toHaveBeenCalledTimes(1);

    // Simulate a second document becoming ready — App.tsx recomputes this
    // signature from the live documents list.
    rerender({ watchKey: "doc-1:ready,doc-2:ready" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getSpy).toHaveBeenCalledTimes(2);
    // Still the stale topic — the backend hasn't flipped to "generating" yet
    // in this mocked sequence.
    expect(result.current.overview?.topics[0]?.title).toBe("Old Topic");

    // The hook must keep polling anyway (this is the fix under test).
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(getSpy).toHaveBeenCalledTimes(3);
    expect(result.current.overview?.status).toBe("generating");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(result.current.overview?.status).toBe("ready");
    expect(result.current.overview?.topics[0]?.title).toBe("New Combined Topic");
  });

  it("eventually stops polling if a watchKey change never leads to a new overview", async () => {
    const getSpy = vi.spyOn(api, "getNotebookOverview").mockResolvedValue(makeOverview());

    const { rerender } = renderHook(({ watchKey }) => useOverview("nb-1", watchKey), {
      initialProps: { watchKey: "doc-1:ready" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    // doc-2 failed rather than becoming ready — no regeneration will ever
    // happen, so the hook's extra "catch up" polling must not run forever.
    rerender({ watchKey: "doc-1:ready,doc-2:failed" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    const callsAfterSettling = getSpy.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30000);
    });
    expect(getSpy.mock.calls.length).toBe(callsAfterSettling);
  });

  it("does not let a regenerate() call started before a notebook switch clobber the new notebook's state", async () => {
    // Regression test: clicking "Try again" on a failed overview, then
    // switching notebooks before the POST resolves, used to let the stale
    // response silently overwrite the newly-selected notebook's state.
    vi.spyOn(api, "getNotebookOverview").mockImplementation(async (id: string) =>
      makeOverview({ notebook_id: id, status: "failed", error_reason: "ollama_unreachable" }),
    );
    let resolveRegenerate: (value: api.OverviewRecord) => void = () => {};
    vi.spyOn(api, "regenerateNotebookOverview").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRegenerate = resolve;
        }),
    );

    const { result, rerender } = renderHook(({ notebookId }) => useOverview(notebookId, "k"), {
      initialProps: { notebookId: "nb-A" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.overview?.notebook_id).toBe("nb-A");

    let regeneratePromise: Promise<void> = Promise.resolve();
    act(() => {
      regeneratePromise = result.current.regenerate();
    });

    // Switch notebooks before the regenerate() POST for nb-A resolves.
    rerender({ notebookId: "nb-B" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.overview?.notebook_id).toBe("nb-B");

    // The stale nb-A regenerate() call finally settles.
    await act(async () => {
      resolveRegenerate(makeOverview({ notebook_id: "nb-A", status: "ready" }));
      await regeneratePromise;
    });

    expect(result.current.overview?.notebook_id).toBe("nb-B");
  });

  it("does not keep polling after unmounting while a fetch is in flight", async () => {
    // Regression test: if a poll's fetch was still in flight when the
    // component unmounted, it used to resolve afterward, pass its own
    // staleness check (nothing had invalidated it), and schedule another
    // poll that no cleanup could ever cancel — polling forever in the
    // background for as long as the page stayed open.
    let resolveFetch: (value: api.OverviewRecord) => void = () => {};
    const getSpy = vi.spyOn(api, "getNotebookOverview").mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveFetch = resolve;
        }),
    );

    const { unmount } = renderHook(() => useOverview("nb-1", "k"));
    unmount();

    await act(async () => {
      resolveFetch(makeOverview({ status: "generating" })); // in-flight fetch settles post-unmount
      await Promise.resolve();
    });
    const callsRightAfterUnmount = getSpy.mock.calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });

    expect(getSpy.mock.calls.length).toBe(callsRightAfterUnmount);
  });
});
