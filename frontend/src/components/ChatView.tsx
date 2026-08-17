import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { useChat } from "../hooks/useChat";
import type { ChatMessageRecord } from "../lib/api";

interface ChatViewProps {
  notebookId: string;
  notebookName: string;
  hasDocuments: boolean;
}

export function ChatView({ notebookId, notebookName, hasDocuments }: ChatViewProps) {
  const { messages, isLoading, historyError, isSending, sendError, sendMessage, editMessage } =
    useChat(notebookId);
  const [draft, setDraft] = useState("");
  const [internetMode, setInternetMode] = useState(false);
  // Only one message can be under edit at a time — starting a new edit
  // implicitly cancels whichever one was open, same as other chat apps.
  const [editingMessageId, setEditingMessageId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, isSending]);

  const isComposerDisabled = isSending || editingMessageId !== null;

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!draft.trim() || isComposerDisabled) return;
    const question = draft;
    setDraft("");
    void sendMessage(question, internetMode);
  };

  const handleEditSave = (messageId: string, content: string) => {
    setEditingMessageId(null);
    void editMessage(messageId, content, internetMode);
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
            {hasDocuments ? (
              <>
                <p className="text-sm font-medium text-ink">Ask a question about this notebook</p>
                <p className="mt-1 max-w-sm text-sm text-ink-muted">
                  Answers are grounded in your uploaded documents. Turn on internet mode below if you
                  want general-knowledge answers too.
                </p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-ink">No documents yet</p>
                <p className="mt-1 max-w-sm text-sm text-ink-muted">
                  Upload a PDF in the Documents tab so answers here can be grounded in it, or turn on
                  internet mode below to ask general-knowledge questions in the meantime.
                </p>
              </>
            )}
          </div>
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
            {messages.map((message) => (
              <ChatBubble
                key={message.id}
                message={message}
                isEditing={editingMessageId === message.id}
                canEdit={!isSending && editingMessageId === null}
                onStartEdit={() => setEditingMessageId(message.id)}
                onCancelEdit={() => setEditingMessageId(null)}
                onSaveEdit={(content) => handleEditSave(message.id, content)}
              />
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
              placeholder={
                editingMessageId !== null ? "Finish editing your question above…" : "Ask a question about your notebook…"
              }
              rows={1}
              disabled={isComposerDisabled}
              aria-label="Your question"
              className="min-h-[42px] flex-1 resize-none rounded-lg border border-line bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={isComposerDisabled || !draft.trim()}
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

function ChatBubble({
  message,
  isEditing,
  canEdit,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
}: {
  message: ChatMessageRecord;
  isEditing: boolean;
  canEdit: boolean;
  onStartEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: (content: string) => void;
}) {
  const isUser = message.role === "user";

  if (isUser && isEditing) {
    return (
      <div className="flex flex-col items-end">
        <EditingComposer initialContent={message.content} onCancel={onCancelEdit} onSave={onSaveEdit} />
      </div>
    );
  }

  return (
    <div className={`group flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div className={`flex items-center gap-1.5 ${isUser ? "flex-row-reverse" : ""}`}>
        <div
          className={`max-w-[85%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
            isUser
              ? "whitespace-pre-wrap bg-brand-subtle text-brand-ink"
              : "border border-line bg-surface text-ink"
          }`}
        >
          {isUser ? message.content : <MarkdownContent content={message.content} />}
        </div>
        <div
          className={`flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 ${isUser ? "flex-row-reverse" : ""}`}
        >
          <CopyButton
            content={message.content}
            label={isUser ? "Copy this question" : "Copy this response"}
          />
          {isUser && canEdit && (
            <button
              type="button"
              onClick={onStartEdit}
              aria-label="Edit this question"
              className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-paper hover:text-ink"
            >
              <EditIcon />
            </button>
          )}
        </div>
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

function EditingComposer({
  initialContent,
  onCancel,
  onSave,
}: {
  initialContent: string;
  onCancel: () => void;
  onSave: (content: string) => void;
}) {
  const [draft, setDraft] = useState(initialContent);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, []);

  const commit = () => {
    const trimmed = draft.trim();
    if (!trimmed) return;
    onSave(trimmed);
  };

  return (
    <div className="w-full max-w-[85%]">
      <textarea
        ref={textareaRef}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            commit();
          } else if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          }
        }}
        rows={Math.min(8, draft.split("\n").length)}
        aria-label="Edit your question"
        className="w-full resize-none rounded-xl border border-brand bg-surface px-4 py-2.5 text-sm leading-relaxed text-ink focus:outline-none"
      />
      <div className="mt-1.5 flex justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-lg px-3 py-1 text-xs font-medium text-ink-muted transition-colors hover:bg-paper hover:text-ink"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={commit}
          disabled={!draft.trim()}
          className="rounded-lg bg-brand px-3 py-1 text-xs font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          Save &amp; submit
        </button>
      </div>
    </div>
  );
}

function MarkdownContent({ content }: { content: string }) {
  return (
    <div className="space-y-2 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
      <Markdown
        components={{
          p: ({ children }) => <p className="leading-relaxed">{children}</p>,
          strong: ({ children }) => <strong className="font-semibold text-ink">{children}</strong>,
          em: ({ children }) => <em className="italic">{children}</em>,
          ul: ({ children }) => <ul className="list-disc space-y-1 pl-5">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal space-y-1 pl-5">{children}</ol>,
          li: ({ children }) => <li>{children}</li>,
          a: ({ children, href }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-brand underline">
              {children}
            </a>
          ),
          h1: ({ children }) => <p className="font-semibold text-ink">{children}</p>,
          h2: ({ children }) => <p className="font-semibold text-ink">{children}</p>,
          h3: ({ children }) => <p className="font-semibold text-ink">{children}</p>,
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-line pl-3 text-ink-muted italic">
              {children}
            </blockquote>
          ),
          code: ({ children }) => (
            <code className="rounded bg-paper px-1 py-0.5 font-mono text-xs">{children}</code>
          ),
          pre: ({ children }) => (
            <pre className="overflow-x-auto rounded-lg bg-paper p-3 font-mono text-xs">{children}</pre>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}

const COPY_CONFIRMATION_MS = 1500;

function CopyButton({ content, label }: { content: string; label: string }) {
  const [isCopied, setIsCopied] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  const handleClick = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setIsCopied(true);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(() => setIsCopied(false), COPY_CONFIRMATION_MS);
    } catch {
      // Clipboard access can be denied by the browser — silently no-op
      // rather than surfacing an error for a non-critical convenience action.
    }
  };

  return (
    <button
      type="button"
      onClick={() => void handleClick()}
      aria-label={isCopied ? "Copied" : label}
      className="rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-paper hover:text-ink"
    >
      {isCopied ? <CheckIcon /> : <CopyIcon />}
    </button>
  );
}

function CopyIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className="h-3.5 w-3.5"
    >
      <rect x="8" y="8" width="12" height="12" rx="2" strokeLinecap="round" strokeLinejoin="round" />
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className="h-3.5 w-3.5 text-status-ready"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m5 13 4 4L19 7" />
    </svg>
  );
}

function EditIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      className="h-3.5 w-3.5"
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m16.5 4.5 3 3L9 18l-4 1 1-4Z" />
    </svg>
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
