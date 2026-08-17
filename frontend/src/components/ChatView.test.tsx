import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { ChatView } from "./ChatView";

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

describe("ChatView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an empty state when there's no conversation yet", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);

    expect(await screen.findByText(/ask a question about this notebook/i)).toBeInTheDocument();
  });

  it("renders existing conversation history with citations", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ id: "m1", role: "user", content: "How are neural networks trained?" }),
      makeMessage({
        id: "m2",
        role: "assistant",
        content: "Via backpropagation.",
        citations: [{ document_id: "d1", filename: "notes.pdf", page_number: 3 }],
      }),
    ]);

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);

    expect(await screen.findByText("How are neural networks trained?")).toBeInTheDocument();
    expect(screen.getByText("Via backpropagation.")).toBeInTheDocument();
    expect(screen.getByText(/notes\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/p\.3/)).toBeInTheDocument();
  });

  it("shows a general-knowledge badge for internet-mode answers", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ used_internet: true, grounded: false, content: "General knowledge answer." }),
    ]);

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);

    expect(await screen.findByText("General knowledge answer.")).toBeInTheDocument();
    expect(screen.getByText(/from general knowledge, not your material/i)).toBeInTheDocument();
  });

  it("sends a question and shows the reply", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);
    vi.spyOn(api, "askChatQuestion").mockResolvedValue(makeMessage({ content: "The answer." }));
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);
    await screen.findByText(/ask a question about this notebook/i);

    await user.type(screen.getByLabelText(/your question/i), "What is X?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    expect(await screen.findByText("What is X?")).toBeInTheDocument();
    expect(await screen.findByText("The answer.")).toBeInTheDocument();
    expect(api.askChatQuestion).toHaveBeenCalledWith("nb-1", "What is X?", false);
  });

  it("passes internet mode through when the toggle is checked", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);
    vi.spyOn(api, "askChatQuestion").mockResolvedValue(makeMessage({ content: "An answer." }));
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);
    await screen.findByText(/ask a question about this notebook/i);

    await user.click(screen.getByRole("checkbox", { name: /internet mode/i }));
    await user.type(screen.getByLabelText(/your question/i), "What is X?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => expect(api.askChatQuestion).toHaveBeenCalledWith("nb-1", "What is X?", true));
  });

  it("clears the composer after sending", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);
    vi.spyOn(api, "askChatQuestion").mockResolvedValue(makeMessage({ content: "An answer." }));
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);
    await screen.findByText(/ask a question about this notebook/i);

    const input = screen.getByLabelText(/your question/i);
    await user.type(input, "What is X?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    await waitFor(() => expect(input).toHaveValue(""));
  });

  it("shows an error if the question fails, without losing the question from view", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);
    vi.spyOn(api, "askChatQuestion").mockRejectedValue(new api.ApiError(503, "AI service unreachable."));
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);
    await screen.findByText(/ask a question about this notebook/i);

    await user.type(screen.getByLabelText(/your question/i), "What is X?");
    await user.click(screen.getByRole("button", { name: /^ask$/i }));

    expect(await screen.findByText("What is X?")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent(/ai service unreachable/i);
  });

  it("renders assistant markdown (bold, lists, code) instead of raw asterisks and dashes", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({
        content: "**MongoDB** is a NoSQL database.\n\n- Uses `mongod`\n- Uses `mongosh`",
      }),
    ]);

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);

    expect(await screen.findByText("MongoDB")).toBeInTheDocument();
    expect(screen.getByText("MongoDB").tagName).toBe("STRONG");
    expect(screen.getByText("mongod").tagName).toBe("CODE");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    // Raw markdown syntax must not leak through as literal text.
    expect(screen.queryByText(/\*\*MongoDB\*\*/)).not.toBeInTheDocument();
  });

  it("puts a past question back in the composer for editing instead of rewriting history", async () => {
    // There's no backend support for editing/truncating history in place, so
    // "edit" repopulates the composer with the original question — the user
    // tweaks it and resends as a new turn, leaving the original intact.
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ id: "m1", role: "user", content: "What is MongoDB?" }),
      makeMessage({ id: "m2", role: "assistant", content: "A NoSQL database." }),
    ]);
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" />);
    await screen.findByText("What is MongoDB?");

    await user.click(screen.getByRole("button", { name: /edit this question/i }));

    expect(screen.getByLabelText(/your question/i)).toHaveValue("What is MongoDB?");
    // The original message is untouched — still visible in history (once in
    // the chat bubble, once as the composer's now-editable value).
    expect(screen.getAllByText("What is MongoDB?")).toHaveLength(2);
  });
});
