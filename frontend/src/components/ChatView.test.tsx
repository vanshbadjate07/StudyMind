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

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText(/ask a question about this notebook/i)).toBeInTheDocument();
  });

  it("shows an upload prompt instead when the notebook has no documents yet", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments={false} />);

    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/ask a question about this notebook/i)).not.toBeInTheDocument();
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

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText("How are neural networks trained?")).toBeInTheDocument();
    expect(screen.getByText("Via backpropagation.")).toBeInTheDocument();
    expect(screen.getByText(/notes\.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/p\.3/)).toBeInTheDocument();
  });

  it("shows a general-knowledge badge for internet-mode answers", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ used_internet: true, grounded: false, content: "General knowledge answer." }),
    ]);

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText("General knowledge answer.")).toBeInTheDocument();
    expect(screen.getByText(/from general knowledge, not your material/i)).toBeInTheDocument();
  });

  it("sends a question and shows the reply", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([]);
    vi.spyOn(api, "askChatQuestion").mockResolvedValue(makeMessage({ content: "The answer." }));
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
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

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
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

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
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

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
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

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText("MongoDB")).toBeInTheDocument();
    expect(screen.getByText("MongoDB").tagName).toBe("STRONG");
    expect(screen.getByText("mongod").tagName).toBe("CODE");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    // Raw markdown syntax must not leak through as literal text.
    expect(screen.queryByText(/\*\*MongoDB\*\*/)).not.toBeInTheDocument();
  });

  it("edits a past question in place, like modern AI chat apps, replacing it and its old answer", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ id: "m1", role: "user", content: "What is MongoDB?" }),
      makeMessage({ id: "m2", role: "assistant", content: "A NoSQL database." }),
    ]);
    vi.spyOn(api, "editChatQuestion").mockResolvedValue(
      makeMessage({ id: "m3", role: "assistant", content: "A document-oriented database." }),
    );
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText("What is MongoDB?");

    await user.click(screen.getByRole("button", { name: /edit this question/i }));

    // The bubble itself becomes an editable textarea, pre-filled in place —
    // not a copy sent down to the composer.
    const editBox = screen.getByLabelText(/edit your question/i);
    expect(editBox).toHaveValue("What is MongoDB?");
    await user.clear(editBox);
    await user.type(editBox, "What is a document database?");
    await user.click(screen.getByRole("button", { name: /save & submit/i }));

    expect(api.editChatQuestion).toHaveBeenCalledWith(
      "nb-1",
      "m1",
      "What is a document database?",
      false,
    );
    expect(await screen.findByText("A document-oriented database.")).toBeInTheDocument();
    // The old question and its old answer are gone, replaced in place.
    expect(screen.queryByText("What is MongoDB?")).not.toBeInTheDocument();
    expect(screen.queryByText("A NoSQL database.")).not.toBeInTheDocument();
    expect(screen.getByText("What is a document database?")).toBeInTheDocument();
  });

  it("cancels an in-progress edit without changing anything", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ id: "m1", role: "user", content: "What is MongoDB?" }),
      makeMessage({ id: "m2", role: "assistant", content: "A NoSQL database." }),
    ]);
    const editSpy = vi.spyOn(api, "editChatQuestion");
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText("What is MongoDB?");

    await user.click(screen.getByRole("button", { name: /edit this question/i }));
    await user.type(screen.getByLabelText(/edit your question/i), " please");
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(editSpy).not.toHaveBeenCalled();
    expect(screen.getByText("What is MongoDB?")).toBeInTheDocument();
    expect(screen.getByText("A NoSQL database.")).toBeInTheDocument();
  });

  it("copies a question's text to the clipboard", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ id: "m1", role: "user", content: "What is MongoDB?" }),
    ]);
    const writeTextSpy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText("What is MongoDB?");

    await user.click(screen.getByRole("button", { name: /copy this question/i }));

    expect(writeTextSpy).toHaveBeenCalledWith("What is MongoDB?");
    expect(await screen.findByRole("button", { name: /^copied$/i })).toBeInTheDocument();
  });

  it("copies an assistant response's text to the clipboard", async () => {
    vi.spyOn(api, "listChatMessages").mockResolvedValue([
      makeMessage({ id: "m1", role: "assistant", content: "MongoDB is a NoSQL database." }),
    ]);
    const writeTextSpy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(<ChatView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText("MongoDB is a NoSQL database.");

    await user.click(screen.getByRole("button", { name: /copy this response/i }));

    expect(writeTextSpy).toHaveBeenCalledWith("MongoDB is a NoSQL database.");
    expect(await screen.findByRole("button", { name: /^copied$/i })).toBeInTheDocument();
  });
});
