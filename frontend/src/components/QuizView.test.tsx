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

  it("shows a generate button when there are documents but no quiz yet", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);
    vi.spyOn(api, "generateNotebookQuiz").mockResolvedValue(makeQuiz({ status: "generating" }));
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByRole("button", { name: /generate quiz/i });

    await user.click(screen.getByRole("button", { name: /generate quiz/i }));

    expect(api.generateNotebookQuiz).toHaveBeenCalledWith("nb-1");
  });

  it("shows an error with a retry button when generation failed", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(
      makeQuiz({ status: "failed", error_reason: "ollama_unreachable" }),
    );

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't reach the ai service/i);
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });

  it("renders every question with four options once the quiz is ready", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText(/what is 2 \+ 2\?/i)).toBeInTheDocument();
    expect(screen.getByText(/what is the capital of france\?/i)).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(8);
  });

  it("disables Submit until every question is answered", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    const submit = screen.getByRole("button", { name: /^submit$/i });
    expect(submit).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "4" }));
    expect(submit).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: "Paris" }));
    expect(submit).toBeEnabled();
  });

  it("scores the attempt and shows explanations after submitting", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "4" })); // correct
    await user.click(screen.getByRole("radio", { name: "Berlin" })); // wrong
    await user.click(screen.getByRole("button", { name: /^submit$/i }));

    expect(await screen.findByText("1 / 2 correct")).toBeInTheDocument();
    expect(screen.getByText("2 + 2 = 4.")).toBeInTheDocument();
    expect(screen.getByText("Paris is the capital of France.")).toBeInTheDocument();
  });

  it("retake resets the attempt without calling the API again", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const generateSpy = vi.spyOn(api, "generateNotebookQuiz");
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "4" }));
    await user.click(screen.getByRole("radio", { name: "Paris" }));
    await user.click(screen.getByRole("button", { name: /^submit$/i }));
    await screen.findByText("2 / 2 correct");

    await user.click(screen.getByRole("button", { name: /retake/i }));

    expect(screen.queryByText("2 / 2 correct")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^submit$/i })).toBeDisabled();
    expect(generateSpy).not.toHaveBeenCalled();
  });

  it("'New questions' regenerates the quiz", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    vi.spyOn(api, "generateNotebookQuiz").mockResolvedValue(makeQuiz({ status: "generating" }));
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("button", { name: /new questions/i }));

    await waitFor(() => expect(api.generateNotebookQuiz).toHaveBeenCalledWith("nb-1"));
  });
});
