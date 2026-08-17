import { useCallback, useEffect, useState } from "react";
import { ApiError, askChatQuestion, listChatMessages, type ChatMessageRecord } from "../lib/api";

export function useChat(notebookId: string | null) {
  const [messages, setMessages] = useState<ChatMessageRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);

  useEffect(() => {
    if (notebookId === null) {
      setMessages([]);
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setHistoryError(null);
    void (async () => {
      try {
        const fetched = await listChatMessages(notebookId);
        if (!cancelled) setMessages(fetched);
      } catch (err) {
        if (!cancelled) {
          setHistoryError(err instanceof ApiError ? err.message : "Couldn't load the conversation.");
        }
      } finally {
        if (!cancelled) setIsLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [notebookId]);

  const sendMessage = useCallback(
    async (question: string, internetMode: boolean) => {
      if (notebookId === null) return;
      const trimmed = question.trim();
      if (!trimmed) return;

      // Optimistic: the user's question is echoed immediately rather than
      // waiting on the round trip — the backend persists it with identical
      // content regardless of how the answer turns out, so there's nothing
      // to reconcile once the request settles. This local copy keeps its
      // synthetic "optimistic-*" id forever (never swapped for the real DB
      // row's id) — harmless today since nothing keys off a user message's
      // id, but worth knowing if a future feature (e.g. retry-in-place,
      // edit/delete a message) needs the real one.
      const optimisticUserMessage: ChatMessageRecord = {
        id: `optimistic-${Date.now()}`,
        role: "user",
        content: trimmed,
        citations: [],
        grounded: false,
        used_internet: false,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimisticUserMessage]);
      setIsSending(true);
      setSendError(null);
      try {
        const assistantMessage = await askChatQuestion(notebookId, trimmed, internetMode);
        setMessages((prev) => [...prev, assistantMessage]);
      } catch (err) {
        setSendError(err instanceof ApiError ? err.message : "Couldn't reach the AI service.");
      } finally {
        setIsSending(false);
      }
    },
    [notebookId],
  );

  return { messages, isLoading, historyError, isSending, sendError, sendMessage };
}
