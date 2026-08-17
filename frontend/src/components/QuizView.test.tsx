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

  it("shows one question at a time and reveals the answer only after submitting", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    expect(screen.queryByText(/what is the capital of france\?/i)).not.toBeInTheDocument();
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();

    const submit = screen.getByRole("button", { name: /^submit$/i });
    expect(submit).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "4" }));
    expect(submit).toBeEnabled();
    expect(screen.queryByText("2 + 2 = 4.")).not.toBeInTheDocument();

    await user.click(submit);

    // Answer revealed immediately for this question, before moving on.
    expect(screen.getByText("2 + 2 = 4.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "4" })).toHaveClass("border-status-ready");
    expect(screen.getByRole("button", { name: /next question/i })).toBeInTheDocument();
  });

  it("advances to the next question and shows a final score at the end", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "4" })); // correct
    await user.click(screen.getByRole("button", { name: /^submit$/i }));
    await user.click(screen.getByRole("button", { name: /next question/i }));

    expect(await screen.findByText(/what is the capital of france\?/i)).toBeInTheDocument();
    expect(screen.getByText("Question 2 of 2")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Berlin" })); // wrong
    await user.click(screen.getByRole("button", { name: /^submit$/i }));
    await user.click(screen.getByRole("button", { name: /see results/i }));

    expect(await screen.findByText("1 / 2 correct")).toBeInTheDocument();
  });

  it("retake resets to question one without calling the API again", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const generateSpy = vi.spyOn(api, "generateNotebookQuiz");
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "4" }));
    await user.click(screen.getByRole("button", { name: /^submit$/i }));
    await user.click(screen.getByRole("button", { name: /next question/i }));
    await user.click(screen.getByRole("radio", { name: "Paris" }));
    await user.click(screen.getByRole("button", { name: /^submit$/i }));
    await user.click(screen.getByRole("button", { name: /see results/i }));
    await screen.findByText("2 / 2 correct");

    await user.click(screen.getByRole("button", { name: /retake/i }));

    expect(screen.getByText(/what is 2 \+ 2\?/i)).toBeInTheDocument();
    expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();
    expect(generateSpy).not.toHaveBeenCalled();
  });

  it("'New questions' from the results screen reopens the setup form", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "4" }));
    await user.click(screen.getByRole("button", { name: /^submit$/i }));
    await user.click(screen.getByRole("button", { name: /next question/i }));
    await user.click(screen.getByRole("radio", { name: "Paris" }));
    await user.click(screen.getByRole("button", { name: /^submit$/i }));
    await user.click(screen.getByRole("button", { name: /see results/i }));
    await screen.findByText("2 / 2 correct");

    await user.click(screen.getByRole("button", { name: /new questions/i }));

    expect(await screen.findByText(/set up your quiz/i)).toBeInTheDocument();
  });

  it("'Reconfigure' mid-quiz reopens the setup form without losing the old quiz", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("button", { name: /reconfigure/i }));

    expect(await screen.findByText(/set up your quiz/i)).toBeInTheDocument();
  });

  it("submitting setup again after reconfiguring calls the API with new options", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    vi.spyOn(api, "generateNotebookQuiz").mockResolvedValue(makeQuiz({ status: "generating" }));
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("button", { name: /reconfigure/i }));
    await screen.findByText(/set up your quiz/i);
    await user.click(screen.getByRole("button", { name: /generate quiz/i }));

    await waitFor(() =>
      expect(api.generateNotebookQuiz).toHaveBeenCalledWith(
        "nb-1",
        expect.objectContaining({ question_count: 8, difficulty: "mixed" }),
      ),
    );
  });
});
