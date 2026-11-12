import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { usePresentation } from "./usePresentation";

function makePresentation(
  overrides: Partial<api.PresentationRecord> = {},
): api.PresentationRecord {
  return {
    id: "pres-1",
    notebook_id: "nb-1",
    status: "ready",
    slide_count: 10,
    style: "concise",
    focus: null,
    error_reason: null,
    error_detail: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("usePresentation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("loads the current presentation state on mount", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(makePresentation());

    const { result } = renderHook(() => usePresentation("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.presentation?.status).toBe("ready");
  });

  it("returns null when no deck has been generated yet", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(null);

    const { result } = renderHook(() => usePresentation("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.presentation).toBeNull();
  });

  it("keeps polling while generating, and stops once ready", async () => {
    const getSpy = vi
      .spyOn(api, "getNotebookPresentation")
      .mockResolvedValueOnce(makePresentation({ status: "generating" }))
      .mockResolvedValueOnce(makePresentation({ status: "generating" }))
      .mockResolvedValue(makePresentation({ status: "ready" }));

    renderHook(() => usePresentation("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(getSpy).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(getSpy).toHaveBeenCalledTimes(3);

    // Settled — the interval must not keep running.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(getSpy).toHaveBeenCalledTimes(3);
  });

  it("stops polling once generation fails", async () => {
    const getSpy = vi
      .spyOn(api, "getNotebookPresentation")
      .mockResolvedValueOnce(makePresentation({ status: "generating" }))
      .mockResolvedValue(
        makePresentation({ status: "failed", error_reason: "llm_unreachable", slide_count: null }),
      );

    const { result } = renderHook(() => usePresentation("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(result.current.presentation?.status).toBe("failed");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(20000);
    });
    expect(getSpy).toHaveBeenCalledTimes(2);
  });

  it("surfaces a load failure as a message instead of throwing", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockRejectedValue(
      new api.ApiError(500, "Server exploded"),
    );

    const { result } = renderHook(() => usePresentation("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.error).toBe("Server exploded");
    expect(result.current.isLoading).toBe(false);
  });

  it("generate() starts polling from the returned pending record", async () => {
    vi.spyOn(api, "getNotebookPresentation")
      .mockResolvedValueOnce(null)
      .mockResolvedValue(makePresentation({ status: "ready" }));
    const generateSpy = vi
      .spyOn(api, "generateNotebookPresentation")
      .mockResolvedValue(makePresentation({ status: "pending", slide_count: null }));

    const { result } = renderHook(() => usePresentation("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await result.current.generate({ slide_count: 12, style: "exam_focused" });
    });
    expect(generateSpy).toHaveBeenCalledWith("nb-1", { slide_count: 12, style: "exam_focused" });
    expect(result.current.presentation?.status).toBe("pending");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(result.current.presentation?.status).toBe("ready");
  });

  it("surfaces a generate failure without clobbering the existing deck", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(makePresentation());
    vi.spyOn(api, "generateNotebookPresentation").mockRejectedValue(
      new api.ApiError(409, "Presentation generation is already in progress for this notebook."),
    );

    const { result } = renderHook(() => usePresentation("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await result.current.generate({ slide_count: 10, style: "concise" });
    });

    expect(result.current.error).toMatch(/already in progress/i);
    expect(result.current.presentation?.status).toBe("ready");
    expect(result.current.isGenerating).toBe(false);
  });

  it("ignores a late response from a notebook the hook has moved off", async () => {
    const getSpy = vi.spyOn(api, "getNotebookPresentation").mockImplementation(async (id) => {
      return makePresentation({ notebook_id: id, slide_count: id === "nb-1" ? 10 : 20 });
    });

    const { result, rerender } = renderHook(({ id }) => usePresentation(id), {
      initialProps: { id: "nb-1" },
    });
    rerender({ id: "nb-2" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.presentation?.notebook_id).toBe("nb-2");
    expect(getSpy).toHaveBeenCalledWith("nb-2");
  });
});
