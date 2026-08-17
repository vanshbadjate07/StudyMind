import { useEffect, useRef, useState } from "react";
import { useChat } from "../hooks/useChat";
import type { ChatMessageRecord } from "../lib/api";

interface ChatViewProps {
  notebookId: string;
  notebookName: string;
}

export function ChatView({ notebookId, notebookName }: ChatViewProps) {
  const { messages, isLoading, historyError, isSending, sendError, sendMessage } = useChat(notebookId);
  const [draft, setDraft] = useState("");
  const [internetMode, setInternetMode] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isSending]);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.trim() || isSending) return;
    const question = draft;
    setDraft("");
    void sendMessage(question, internetMode);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-6 py-4 lg:px-12">
        <h1 className="text-lg font-semibold tracking-tight text-ink">Chat</h1>
        <p className="mt-0.5 text-xs text-ink-muted">
          Ask questions about the documents in "{notebookName}".
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 lg:px-12">
        {isLoading ? (
          <ChatSkeleton />
        ) : historyError ? (
          <p role="alert" className="text-sm text-status-failed">
            {historyError}
          </p>
        ) : messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <p className="text-sm font-medium text-ink">Ask a question about this notebook</p>
            <p className="mt-1 max-w-sm text-sm text-ink-muted">
              Answers are grounded in your uploaded documents. Turn on internet mode below if you want
              general-knowledge answers too.
            </p>
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
            {messages.map((message) => (
              <ChatBubble key={message.id} message={message} />
            ))}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-line px-6 py-4 lg:px-12">
        <form onSubmit={handleSubmit} className="mx-auto flex w-full max-w-3xl flex-col gap-2">
          {sendError && (
            <p role="alert" className="text-xs text-status-failed">
              {sendError}
            </p>
          )}
          <div className="flex items-end gap-2">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  handleSubmit(event);
                }
              }}
              placeholder="Ask a question about your notebook…"
              rows={1}
              disabled={isSending}
              aria-label="Your question"
              className="min-h-[42px] flex-1 resize-none rounded-lg border border-line bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={isSending || !draft.trim()}
              className="shrink-0 rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {isSending ? "Asking…" : "Ask"}
            </button>
          </div>
          <label className="flex w-fit cursor-pointer items-center gap-2 text-xs text-ink-muted">
            <input
              type="checkbox"
              checked={internetMode}
              onChange={(event) => setInternetMode(event.target.checked)}
              className="h-3.5 w-3.5 rounded border-line-strong accent-brand"
            />
            Internet mode — allow general-knowledge answers beyond your material
          </label>
        </form>
      </div>
    </div>
  );
}

function ChatBubble({ message }: { message: ChatMessageRecord }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
          isUser ? "bg-brand-subtle text-brand-ink" : "border border-line bg-surface text-ink"
        }`}
      >
        {message.content}
      </div>
      {!isUser && message.used_internet && (
        <span className="mt-1.5 inline-flex items-center gap-1 rounded-full border border-line-strong px-2 py-0.5 text-[11px] font-medium text-ink-muted">
          From general knowledge, not your material
        </span>
      )}
      {!isUser && message.citations.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {message.citations.map((citation, index) => (
            <span
              key={`${index}-${citation.document_id}-${citation.page_number}`}
              className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-muted"
            >
              {citation.filename}
              {citation.page_number !== null ? ` · p.${citation.page_number}` : ""}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ChatSkeleton() {
  return (
    <div className="mx-auto w-full max-w-3xl space-y-3" aria-busy="true" aria-label="Loading conversation">
      <div className="ml-auto h-9 w-2/5 animate-pulse rounded-xl bg-line/60" />
      <div className="h-16 w-3/5 animate-pulse rounded-xl bg-line/60" />
    </div>
  );
}
