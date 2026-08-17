import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { useQuiz } from "./useQuiz";

function makeQuiz(overrides: Partial<api.QuizRecord> = {}): api.QuizRecord {
  return {
    id: "quiz-1",
    notebook_id: "nb-1",
    status: "ready",
    questions: [{ question: "Q?", options: ["A", "B", "C", "D"], correct_index: 0, explanation: "e" }],
    error_reason: null,
    error_detail: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("useQuiz", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("loads the current quiz state on mount", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());

    const { result } = renderHook(() => useQuiz("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.quiz?.status).toBe("ready");
  });

  it("returns null when no quiz has been generated yet", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);

    const { result } = renderHook(() => useQuiz("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.quiz).toBeNull();
  });

  it("keeps polling while the quiz is generating, and stops once ready", async () => {
    const getSpy = vi
      .spyOn(api, "getNotebookQuiz")
      .mockResolvedValueOnce(makeQuiz({ status: "generating" }))
      .mockResolvedValueOnce(makeQuiz({ status: "generating" }))
      .mockResolvedValue(makeQuiz({ status: "ready" }));

    renderHook(() => useQuiz("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(getSpy).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(getSpy).toHaveBeenCalledTimes(3);

    // Settled now — no further polling.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(getSpy).toHaveBeenCalledTimes(3);
  });

  it("generate() starts a fresh quiz and polls it to completion", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);
    const generateSpy = vi
      .spyOn(api, "generateNotebookQuiz")
      .mockResolvedValue(makeQuiz({ status: "generating" }));
    const getSpy = vi.spyOn(api, "getNotebookQuiz");

    const { result } = renderHook(() => useQuiz("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.quiz).toBeNull();

    getSpy.mockResolvedValue(makeQuiz({ status: "ready" }));
    await act(async () => {
      await result.current.generate();
    });

    expect(generateSpy).toHaveBeenCalledWith("nb-1");
    expect(result.current.quiz?.status).toBe("generating");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500);
    });
    expect(result.current.quiz?.status).toBe("ready");
  });

  it("surfaces an error when generate() fails", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);
    vi.spyOn(api, "generateNotebookQuiz").mockRejectedValue(
      new api.ApiError(409, "No ready documents in this notebook yet."),
    );

    const { result } = renderHook(() => useQuiz("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await result.current.generate();
    });

    expect(result.current.error).toBe("No ready documents in this notebook yet.");
  });

  it("surfaces a history-load error", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockRejectedValue(new api.ApiError(500, "Server error."));

    const { result } = renderHook(() => useQuiz("nb-1"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    expect(result.current.error).toBe("Server error.");
  });
});
