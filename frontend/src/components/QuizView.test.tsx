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

  it("shows the setup form, defaulted to 8 mixed-difficulty questions", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText(/set up your quiz/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/number of questions/i)).toHaveValue(8);
    expect(screen.getByRole("button", { name: /^mixed/i })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/generates 8 mixed-difficulty questions/i)).toBeInTheDocument();
  });

  it("stepper buttons and preset chips both adjust the question count, reflected in the summary", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    const countInput = await screen.findByLabelText(/number of questions/i);

    await user.click(screen.getByRole("button", { name: /increase question count/i }));
    expect(countInput).toHaveValue(9);

    await user.click(screen.getByRole("button", { name: /decrease question count/i }));
    await user.click(screen.getByRole("button", { name: /decrease question count/i }));
    expect(countInput).toHaveValue(7);

    await user.click(screen.getByRole("button", { name: "15" }));
    expect(countInput).toHaveValue(15);
    expect(screen.getByText(/generates 15 mixed-difficulty questions/i)).toBeInTheDocument();
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

  it("submits the chosen customization options to generate the quiz", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);
    vi.spyOn(api, "generateNotebookQuiz").mockResolvedValue(makeQuiz({ status: "generating" }));
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/set up your quiz/i);

    await user.click(screen.getByRole("button", { name: "5" }));
    await user.click(screen.getByRole("button", { name: /^hard/i }));
    await user.type(screen.getByLabelText(/focus on/i), "neural networks");
    await user.click(screen.getByRole("switch", { name: /allow general knowledge/i }));
    await user.click(screen.getByRole("button", { name: /generate quiz/i }));

    expect(api.generateNotebookQuiz).toHaveBeenCalledWith("nb-1", {
      question_count: 5,
      difficulty: "hard",
      allow_general_knowledge: true,
      focus: "neural networks",
    });
  });

  it("shows an error with a retry that reopens setup when generation failed", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(
      makeQuiz({ status: "failed", error_reason: "llm_unreachable" }),
    );
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't reach the ai service/i);

    await user.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByText(/set up your quiz/i)).toBeInTheDocument();
  });

  it("shows every question at once, ungraded until each is individually submitted", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    expect(screen.getByText(/what is the capital of france\?/i)).toBeInTheDocument();
    expect(screen.getAllByRole("radio")).toHaveLength(8);
    expect(screen.getByText("0 of 2 answered")).toBeInTheDocument();

    const submitButtons = screen.getAllByRole("button", { name: /submit answer/i });
    expect(submitButtons).toHaveLength(2);
    expect(submitButtons[0]).toBeDisabled();

    // Selecting an option does not grade it by itself.
    await user.click(screen.getByRole("radio", { name: "4" }));
    expect(screen.queryByText("2 + 2 = 4.")).not.toBeInTheDocument();
    expect(screen.getByText("0 of 2 answered")).toBeInTheDocument();
    expect(submitButtons[0]).toBeEnabled();
  });

  it("lets you change your mind before submitting, then locks the answer in on submit", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "3" })); // change mind before submitting
    await user.click(screen.getByRole("radio", { name: "4" }));
    expect(screen.getByRole("radio", { name: "4" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("radio", { name: "3" })).toHaveAttribute("aria-checked", "false");

    const [submitFirst] = screen.getAllByRole("button", { name: /submit answer/i });
    await user.click(submitFirst);

    expect(screen.getByText("2 + 2 = 4.")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "4" })).toHaveClass("border-status-ready");
    expect(screen.getByRole("radio", { name: "3" })).toBeDisabled();
    expect(screen.getByText("1 of 2 answered")).toBeInTheDocument();
    expect(screen.getByText("1 / 1 correct so far")).toBeInTheDocument();
  });

  it("shows a live running score that becomes the final score once every question is submitted", async () => {
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(makeQuiz());
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/what is 2 \+ 2\?/i);

    await user.click(screen.getByRole("radio", { name: "4" })); // correct
    await user.click(screen.getAllByRole("button", { name: /submit answer/i })[0]);
    expect(screen.getByText("1 / 1 correct so far")).toBeInTheDocument();

    await user.click(screen.getByRole("radio", { name: "Berlin" })); // wrong
    await user.click(screen.getAllByRole("button", { name: /submit answer/i })[0]);

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
    await user.click(screen.getAllByRole("button", { name: /submit answer/i })[0]);
    await user.click(screen.getByRole("radio", { name: "Paris" }));
    await user.click(screen.getAllByRole("button", { name: /submit answer/i })[0]);
    await screen.findByText("2 / 2 correct");

    await user.click(screen.getByRole("button", { name: /retake/i }));

    expect(screen.getByText("0 of 2 answered")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "4" })).not.toBeDisabled();
    expect(screen.getAllByRole("button", { name: /submit answer/i })[0]).toBeDisabled();
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

  it("shuffles question order when the setup toggle is on", async () => {
    const threeQuestionQuiz = makeQuiz({
      questions: [
        { question: "Question Alpha", options: ["a", "b", "c", "d"], correct_index: 0, explanation: "e" },
        { question: "Question Beta", options: ["a", "b", "c", "d"], correct_index: 0, explanation: "e" },
        { question: "Question Gamma", options: ["a", "b", "c", "d"], correct_index: 0, explanation: "e" },
      ],
    });
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(null);
    vi.spyOn(api, "generateNotebookQuiz").mockResolvedValue(threeQuestionQuiz);
    // Fisher-Yates with Math.random() always 0 is a deterministic
    // permutation: [Alpha, Beta, Gamma] -> [Beta, Gamma, Alpha].
    vi.spyOn(Math, "random").mockReturnValue(0);
    const user = userEvent.setup();

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/set up your quiz/i);

    await user.click(screen.getByRole("switch", { name: /shuffle question order/i }));
    await user.click(screen.getByRole("button", { name: /generate quiz/i }));

    const rendered = await screen.findAllByText(/^\d\. Question (Alpha|Beta|Gamma)$/);
    expect(rendered.map((el) => el.textContent)).toEqual([
      "1. Question Beta",
      "2. Question Gamma",
      "3. Question Alpha",
    ]);
  });

  it("keeps original question order when shuffle is off", async () => {
    const threeQuestionQuiz = makeQuiz({
      questions: [
        { question: "Question Alpha", options: ["a", "b", "c", "d"], correct_index: 0, explanation: "e" },
        { question: "Question Beta", options: ["a", "b", "c", "d"], correct_index: 0, explanation: "e" },
        { question: "Question Gamma", options: ["a", "b", "c", "d"], correct_index: 0, explanation: "e" },
      ],
    });
    vi.spyOn(api, "getNotebookQuiz").mockResolvedValue(threeQuestionQuiz);

    render(<QuizView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    const rendered = await screen.findAllByText(/^\d\. Question (Alpha|Beta|Gamma)$/);
    expect(rendered.map((el) => el.textContent)).toEqual([
      "1. Question Alpha",
      "2. Question Beta",
      "3. Question Gamma",
    ]);
  });
});
