import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { useInterview } from "./useInterview";

function makeTurn(overrides: Partial<api.InterviewTurnRecord> = {}): api.InterviewTurnRecord {
  return {
    id: "turn-1",
    question_index: 0,
    topic: "Hash tables",
    question: "How does a hash table work?",
    is_probe: false,
    answer_text: null,
    score: null,
    feedback: null,
    missed_points: [],
    features: {},
    ideal_answer: null,
    key_concepts: ["hash function"],
    asked_at: "2026-01-01T00:00:00Z",
    answered_at: null,
    ...overrides,
  };
}

function makeSession(
  overrides: Partial<api.InterviewSessionRecord> = {},
): api.InterviewSessionRecord {
  const turns = overrides.turns ?? [makeTurn()];
  return {
    id: "int-1",
    notebook_id: "nb-1",
    mode: "text",
    status: "in_progress",
    question_limit: 8,
    overall_score: null,
    weak_areas: [],
    topics: ["Hash tables", "Threads"],
    turns,
    current_question: turns.find((turn) => turn.answered_at === null) ?? null,
    answered_count: turns.filter((turn) => turn.answered_at !== null).length,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

describe("useInterview", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the notebook's latest interview on mount", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());

    const { result } = renderHook(() => useInterview("nb-1"));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.session?.id).toBe("int-1");
    expect(result.current.error).toBeNull();
  });

  it("returns null when no interview has been started yet", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);

    const { result } = renderHook(() => useInterview("nb-1"));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.session).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("surfaces a load failure", async () => {
    vi.spyOn(api, "getNotebookInterview").mockRejectedValue(new api.ApiError(500, "Server down"));

    const { result } = renderHook(() => useInterview("nb-1"));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBe("Server down");
  });

  it("starts an interview and holds the returned session", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);
    const start = vi.spyOn(api, "startNotebookInterview").mockResolvedValue(makeSession());

    const { result } = renderHook(() => useInterview("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.start({ mode: "text", question_limit: 5 });
    });

    expect(start).toHaveBeenCalledWith("nb-1", { mode: "text", question_limit: 5 });
    expect(result.current.session?.id).toBe("int-1");
    expect(result.current.isStarting).toBe(false);
  });

  it("surfaces a 409 when an interview is already in progress", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);
    vi.spyOn(api, "startNotebookInterview").mockRejectedValue(
      new api.ApiError(409, "An interview is already in progress for this notebook."),
    );

    const { result } = renderHook(() => useInterview("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.start({ mode: "text", question_limit: 5 });
    });

    expect(result.current.error).toMatch(/already in progress/i);
  });

  it("replaces the session wholesale when an answer is submitted", async () => {
    // The API returns the entire session rather than just the new turn, so
    // the hook never has to merge state.
    const answered = makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 80 });
    const next = makeTurn({ id: "turn-2", question_index: 1, question: "And collisions?" });
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());
    const submit = vi
      .spyOn(api, "submitInterviewAnswer")
      .mockResolvedValue(makeSession({ turns: [answered, next] }));

    const { result } = renderHook(() => useInterview("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.submitAnswer("a hash function");
    });

    expect(submit).toHaveBeenCalledWith("int-1", "a hash function");
    expect(result.current.session?.answered_count).toBe(1);
    expect(result.current.session?.current_question?.id).toBe("turn-2");
  });

  it("does nothing when asked to answer with no session loaded", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);
    const submit = vi.spyOn(api, "submitInterviewAnswer");

    const { result } = renderHook(() => useInterview("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.submitAnswer("orphan answer");
    });

    expect(submit).not.toHaveBeenCalled();
  });

  it("ends an interview and keeps the completed report", async () => {
    const answered = makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 64 });
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());
    vi.spyOn(api, "endInterview").mockResolvedValue(
      makeSession({
        status: "completed",
        overall_score: 64,
        turns: [answered],
        completed_at: "2026-01-01T00:02:00Z",
      }),
    );

    const { result } = renderHook(() => useInterview("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.end();
    });

    expect(result.current.session?.status).toBe("completed");
    expect(result.current.session?.overall_score).toBe(64);
  });

  it("resumes an interview left with no pending question", async () => {
    const answered = makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 80 });
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({ turns: [answered] }),
    );
    const resume = vi.spyOn(api, "continueInterview").mockResolvedValue(
      makeSession({ turns: [answered, makeTurn({ id: "turn-2", question_index: 1 })] }),
    );

    const { result } = renderHook(() => useInterview("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.session?.current_question).toBeNull();

    await act(async () => {
      await result.current.resume();
    });

    expect(resume).toHaveBeenCalledWith("int-1");
    expect(result.current.session?.current_question?.id).toBe("turn-2");
  });

  it("clears the report locally without touching the server", async () => {
    const answered = makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 70 });
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({ status: "completed", overall_score: 70, turns: [answered] }),
    );
    const end = vi.spyOn(api, "endInterview");

    const { result } = renderHook(() => useInterview("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    act(() => {
      result.current.dismissReport();
    });

    expect(result.current.session).toBeNull();
    expect(end).not.toHaveBeenCalled();
  });

  it("ignores a reply for a notebook the user has already switched away from", async () => {
    // Same stale-response guard the polling hooks carry: switching notebooks
    // mid-request must not let the old notebook's interview land in state.
    let resolveFirst: ((value: api.InterviewSessionRecord | null) => void) | undefined;
    vi.spyOn(api, "getNotebookInterview").mockImplementation((notebookId: string) => {
      if (notebookId === "nb-1") {
        return new Promise((resolve) => {
          resolveFirst = resolve;
        });
      }
      return Promise.resolve(makeSession({ id: "int-2", notebook_id: "nb-2" }));
    });

    const { result, rerender } = renderHook(({ id }) => useInterview(id), {
      initialProps: { id: "nb-1" },
    });

    rerender({ id: "nb-2" });
    await waitFor(() => expect(result.current.session?.id).toBe("int-2"));

    await act(async () => {
      resolveFirst?.(makeSession({ id: "int-1", notebook_id: "nb-1" }));
    });

    expect(result.current.session?.id).toBe("int-2");
  });
});
