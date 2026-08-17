import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { useChat } from "./useChat";

function makeMessage(overrides: Partial<api.ChatMessageRecord> = {}): api.ChatMessageRecord {
  return {
    id: "msg-1",
    role: "assistant",
    content: "An answer.",
    citations: [],
    grounded: true,
    used_internet: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("useChat", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("loads the conversation history for the given notebook", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ id: "m1", role: "user", content: "Hi" }),
      makeMessage({ id: "m2", role: "assistant", content: "Hello" }),
    ]);

    const { result } = renderHook(() => useChat("nb-1"));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].content).toBe("Hi");
  });

  it("returns no messages and does not call the API when no notebook is selected", async () => {
    const listSpy = vi.spyOn(api, "listChatMessages");
    const { result } = renderHook(() => useChat(null));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.messages).toEqual([]);
    expect(listSpy).not.toHaveBeenCalled();
  });

  it("shows a history error when loading the conversation fails", async () => {
    vi.spyOn(api, "listChatMessages").mockRejectedValue(new api.ApiError(500, "Server error."));

    const { result } = renderHook(() => useChat("nb-1"));

    await waitFor(() => expect(result.current.historyError).toBe("Server error."));
  });

  it("optimistically shows the question, then appends the assistant's reply", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);
    vi.spyOn(api, "askChatQuestion").mockResolvedValue(
      makeMessage({ id: "reply-1", content: "The answer." }),
    );

    const { result } = renderHook(() => useChat("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.sendMessage("What is X?", false);
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({ role: "user", content: "What is X?" });
    expect(result.current.messages[1]).toMatchObject({ role: "assistant", content: "The answer." });
    expect(api.askChatQuestion).toHaveBeenCalledWith("nb-1", "What is X?", false);
  });

  it("keeps the optimistic question visible and surfaces an error if the request fails", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);
    vi.spyOn(api, "askChatQuestion").mockRejectedValue(new api.ApiError(503, "AI service unreachable."));

    const { result } = renderHook(() => useChat("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.sendMessage("What is X?", false);
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.sendError).toBe("AI service unreachable.");
  });

  it("does not send a blank question", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);
    const askSpy = vi.spyOn(api, "askChatQuestion");

    const { result } = renderHook(() => useChat("nb-1"));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.sendMessage("   ", false);
    });

    expect(askSpy).not.toHaveBeenCalled();
    expect(result.current.messages).toEqual([]);
  });
});
