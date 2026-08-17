import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { QuizView } from "./QuizView";

function makeQuiz(overrides: Partial<api.QuizRecord> = {}): api.QuizRecord {
  return {
    id: "quiz-1",
    notebook_id: "nb-1",
    status: "ready",
    questions: [
      {
        question: "What is 2 + 2?",
        options: ["3", "4", "5", "6"],
        correct_index: 1,
        explanation: "2 + 2 = 4.",
      },
      {
        question: "What is the capital of France?",
        options: ["Berlin", "Madrid", "Paris", "Rome"],
        correct_index: 2,
        explanation: "Paris is the capital of France.",
      },
    ],
    error_reason: null,
    error_detail: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("QuizView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an upload prompt when the notebook has no documents yet", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments={false} />);

    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate quiz/i })).not.toBeInTheDocument();
  });

  it("shows the setup form when there are documents but no quiz yet", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText(/set up your quiz/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/number of questions/i)).toHaveValue(8);
    expect(screen.getByRole("button", { name: /^mixed/i })).toHaveAttribute("aria-pressed", "true");
  });

  it("submits the chosen customization options to generate the quiz", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);
    vi.spyOn(api, "generateNotebookQuiz").mockResolvedValue(makeQuiz({ status: "generating" }));
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/set up your quiz/i);

    const countInput = screen.getByLabelText(/number of questions/i);
    await user.clear(countInput);
    await user.type(countInput, "5");
    await user.click(screen.getByRole("button", { name: /^hard/i }));
    await user.type(screen.getByLabelText(/focus on/i), "neural networks");
    await user.click(screen.getByLabelText(/general knowledge/i));
    await user.click(screen.getByRole("button", { name: /generate quiz/i }));

    expect(api.generateNotebookQuiz).toHaveBeenCalledWith("nb-1", {
      question_count: 5,
      difficulty: "hard",
      allow_general_knowledge: true,
      focus: "neural networks",
    });
  });

  it("clamps the question count to the allowed range on blur", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    const countInput = await screen.findByLabelText(/number of questions/i);

    await user.clear(countInput);
    await user.type(countInput, "999");
    await user.tab();

    expect(countInput).toHaveValue(20);
  });

  it("shows an error with a retry that reopens setup when generation failed", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(
      makeQuiz({ status: "failed", error_reason: "ollama_unreachable" }),
    );
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't reach the ai service/i);

    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByText(/set up your quiz/i)).toBeInTheDocument();
  });

  it("shows every question at once", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText(/what is 2 \+ 2\?/i)).toBeInTheDocument();
    expect(screen.getByText(/what is the capital of france\?/i)).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(8);
    expect(screen.getByText("0 of 2 answered")).toBeInTheDocument();
  });

  it("grades a question the instant an option is selected, with no separate submit step", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    expect(screen.queryByRole("button", { name: /^submit$/i })).not.toBeInTheDocument();
    expect(screen.queryByText("2 + 2 = 4.")).not.toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "4" }));

    // Graded immediately — no submit click needed.
    expect(screen.getByText("2 + 2 = 4.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "4" })).toHaveClass("border-status-ready");
    expect(screen.getByText("1 of 2 answered")).toBeInTheDocument();
    expect(screen.getByText("1 / 1 correct so far")).toBeInTheDocument();

    // The other question is untouched and still answerable.
    expect(screen.getByRole("radio", { name: "Paris" })).not.toBeDisabled();
  });

  it("locks in the first choice — clicking another option afterward does nothing", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "3" })); // wrong, locks in
    expect(screen.getByRole("radio", { name: "3" })).toHaveClass("border-status-failed");
    expect(screen.getByRole("radio", { name: "4" })).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "4" })); // attempt to change answer
    // "4" still shows as the correct option (green), but wasn't selected —
    // the original wrong pick ("3") stands, so the score doesn't change.
    expect(screen.getByRole("radio", { name: "4" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByText("0 / 1 correct so far")).toBeInTheDocument();
  });

  it("shows a live running score that becomes the final score once every question is answered", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "4" })); // correct
    expect(screen.getByText("1 / 1 correct so far")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Berlin" })); // wrong
    expect(screen.getByText("Quiz complete")).toBeInTheDocument();
    expect(screen.getByText("1 / 2 correct")).toBeInTheDocument();
  });

  it("retake clears every answer without calling the API again", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const generateSpy = vi.spyOn(api, "generateNotebookQuiz");
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "4" }));
    await user.click(screen.getByRole("radio", { name: "Paris" }));
    await screen.findByText("2 / 2 correct");

    await user.click(screen.getByRole("button", { name: /retake/i }));

    expect(screen.getByText("0 of 2 answered")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "4" })).not.toBeDisabled();
    expect(generateSpy).not.toHaveBeenCalled();
  });

  it("'New questions' reopens the setup form before generating anything new", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    vi.spyOn(api, "generateNotebookQuiz").mockResolvedValue(makeQuiz({ status: "generating" }));
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("button", { name: /new questions/i }));

    expect(await screen.findByText(/set up your quiz/i)).toBeInTheDocument();
    expect(api.generateNotebookQuiz).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: /generate quiz/i }));

    await waitFor(() =>
      expect(api.generateNotebookQuiz).toHaveBeenCalledWith(
        "nb-1",
        expect.objectContaining({ question_count: 8, difficulty: "mixed" }),
      ),
    );
  });
});
