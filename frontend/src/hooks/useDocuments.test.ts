import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { useDocuments } from "./useDocuments";

const readyDoc: api.DocumentRecord = {
  id: "1",
  filename: "a.pdf",
  status: "ready",
  page_count: 1,
  char_count: 10,
  chunk_count: 1,
  error_reason: null,
  error_detail: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const processingDoc: api.DocumentRecord = { ...readyDoc, id: "2", status: "processing" };

describe("useDocuments", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("polls while a document is in-flight and stops once everything settles", async () => {
    const listSpy = vi
      .spyOn(api, "listDocuments")
      .mockResolvedValueOnce([processingDoc])
      .mockResolvedValueOnce([readyDoc]);

    const { result } = renderHook(() => useDocuments());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.isLoading).toBe(false);
    expect(listSpy).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(listSpy).toHaveBeenCalledTimes(2);
    expect(result.current.documents[0]?.status).toBe("ready");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(listSpy).toHaveBeenCalledTimes(2);
  });

  it("does not poll at all if nothing is in-flight from the start", async () => {
    const listSpy = vi.spyOn(api, "listDocuments").mockResolvedValue([readyDoc]);
    const { result } = renderHook(() => useDocuments());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.isLoading).toBe(false);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10000);
    });
    expect(listSpy).toHaveBeenCalledTimes(1);
  });
});
