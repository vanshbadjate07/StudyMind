import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { InterviewView } from "./InterviewView";

function makeTurn(overrides: Partial<api.InterviewTurnRecord> = {}): api.InterviewTurnRecord {
  return {
    id: "turn-1",
    question_index: 0,
    topic: "Hash tables",
    question: "How does a hash table achieve constant-time lookup?",
    is_probe: false,
    answer_text: null,
    score: null,
    feedback: null,
    missed_points: [],
    features: {},
    ideal_answer: null,
    key_concepts: ["hash function", "bucket index"],
    asked_at: "2026-01-01T00:00:00Z",
    answered_at: null,
    ...overrides,
  };
}

function makeSession(
  overrides: Partial<api.InterviewSessionRecord> = {},
): api.InterviewSessionRecord {
  const turns = overrides.turns ?? [makeTurn()];
  return {
    id: "int-1",
    notebook_id: "nb-1",
    mode: "text",
    status: "in_progress",
    question_limit: 8,
    overall_score: null,
    weak_areas: [],
    topics: ["Hash tables", "Threads"],
    turns,
    current_question: turns.find((turn) => turn.answered_at === null) ?? null,
    answered_count: turns.filter((turn) => turn.answered_at !== null).length,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

const METRICS: api.ScoringMetricsRecord = {
  held_out_mae: 1.37,
  held_out_r2: 0.9924,
  model: "GradientBoostingRegressor",
  corpus_size: 312,
  using_fallback: false,
};

const VOICE_AVAILABLE: api.VoiceCapabilityRecord = {
  available: true,
  backend: "cloud",
  detail: null,
};

describe("InterviewView", () => {
  beforeEach(() => {
    vi.spyOn(api, "getScoringMetrics").mockResolvedValue(METRICS);
    // Voice is off unless a test opts in, so the existing expectations stay
    // about the text path.
    vi.spyOn(api, "getVoiceCapability").mockResolvedValue({
      available: false,
      backend: "local",
      detail: "Local speech to text needs faster-whisper.",
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("asks for a document before offering an interview", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments={false} />);

    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /start interview/i })).not.toBeInTheDocument();
  });

  it("shows the setup form with a default question limit of 8", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByRole("button", { name: /start interview/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/maximum questions/i)).toHaveValue(8);
  });

  it("states that scoring is a trained model, with its held-out error", async () => {
    // The scoring note exists so the user can judge the scorer rather than
    // being asked to trust it.
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText(/trained model over five measured features/i)).toBeInTheDocument();
    expect(screen.getByText(/off by 1.37 points/i)).toBeInTheDocument();
  });

  it("says so when the scorer is running on its rule-based fallback", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);
    vi.spyOn(api, "getScoringMetrics").mockResolvedValue({
      held_out_mae: null,
      held_out_r2: null,
      model: null,
      corpus_size: null,
      using_fallback: true,
    });

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText(/rule based fallback/i)).toBeInTheDocument();
  });

  it("starts an interview with the chosen limit and focus", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);
    const start = vi.spyOn(api, "startNotebookInterview").mockResolvedValue(makeSession());
    const user = userEvent.setup();

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByRole("button", { name: /start interview/i });

    await user.click(screen.getByRole("button", { name: /^5$/ }));
    await user.type(screen.getByLabelText(/focus on/i), "hashing");
    await user.click(screen.getByRole("button", { name: /start interview/i }));

    expect(start).toHaveBeenCalledWith("nb-1", {
      mode: "text",
      question_limit: 5,
      focus: "hashing",
    });
  });

  it("shows the current question with an answer box, and hides the model answer", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText(/how does a hash table achieve/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/your answer/i)).toBeInTheDocument();
    expect(screen.getByText(/question 1 of 8/i)).toBeInTheDocument();
    expect(screen.queryByText(/answer from your material/i)).not.toBeInTheDocument();
  });

  it("warns that an empty submission counts as skipping", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText(/counts as skipping/i)).toBeInTheDocument();
  });

  it("submits the typed answer", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());
    const submit = vi.spyOn(api, "submitInterviewAnswer").mockResolvedValue(
      makeSession({
        turns: [
          makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 72, feedback: "Solid answer." }),
          makeTurn({ id: "turn-2", question_index: 1, question: "What about collisions?" }),
        ],
      }),
    );
    const user = userEvent.setup();

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByLabelText(/your answer/i);

    await user.type(screen.getByLabelText(/your answer/i), "It hashes the key to a bucket.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));

    expect(submit).toHaveBeenCalledWith("int-1", "It hashes the key to a bucket.");
    expect(await screen.findByText(/what about collisions/i)).toBeInTheDocument();
  });

  it("shows the score, feedback and missed points for an answered turn", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({
        turns: [
          makeTurn({
            answered_at: "2026-01-01T00:01:00Z",
            answer_text: "It uses a hash function.",
            score: 48,
            feedback: "Partially correct.",
            missed_points: ["collisions", "load factor"],
          }),
          makeTurn({ id: "turn-2", question_index: 1 }),
        ],
      }),
    );

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText("48")).toBeInTheDocument();
    expect(screen.getByText(/partially correct/i)).toBeInTheDocument();
    expect(screen.getByText("collisions")).toBeInTheDocument();
    expect(screen.getByText("load factor")).toBeInTheDocument();
    expect(screen.getByText(/it uses a hash function/i)).toBeInTheDocument();
  });

  it("marks a follow-up question as such, so the adaptation is visible", async () => {
    // The badge is the user-facing evidence that the interview responded to
    // the previous answer rather than reading from a fixed list.
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({
        turns: [
          makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 20, answer_text: "Not sure" }),
          makeTurn({
            id: "turn-2",
            question_index: 1,
            is_probe: true,
            question: "What does a hash function return?",
          }),
        ],
      }),
    );

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText(/what does a hash function return/i)).toBeInTheDocument();
    expect(screen.getByText(/follow up/i)).toBeInTheDocument();
  });

  it("reveals the model answer and the score breakdown on request", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({
        turns: [
          makeTurn({
            answered_at: "2026-01-01T00:01:00Z",
            answer_text: "A hash function.",
            score: 55,
            feedback: "Partially correct.",
            ideal_answer: "It hashes the key to a bucket index, and chains collisions.",
            features: { semantic_similarity: 0.62, concept_coverage: 0.5 },
          }),
        ],
        status: "completed",
        overall_score: 55,
        completed_at: "2026-01-01T00:02:00Z",
      }),
    );
    const user = userEvent.setup();

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByText(/partially correct/i);

    await user.click(screen.getByRole("button", { name: /show model answer/i }));

    expect(screen.getByText(/answer from your material/i)).toBeInTheDocument();
    expect(screen.getByText(/it hashes the key to a bucket index/i)).toBeInTheDocument();
    expect(screen.getByText(/closeness to the model answer/i)).toBeInTheDocument();
    expect(screen.getByText(/key points covered/i)).toBeInTheDocument();
  });

  it("shows the final report with the overall score and weak areas", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({
        status: "completed",
        overall_score: 42,
        weak_areas: ["Hash tables"],
        completed_at: "2026-01-01T00:05:00Z",
        turns: [
          makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 42, answer_text: "Partial." }),
        ],
      }),
    );

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    const report = await screen.findByRole("region", { name: /interview report/i });
    // Scoped to the report: the same number also appears on the turn it came
    // from, further down the transcript.
    expect(within(report).getByText("42")).toBeInTheDocument();
    expect(within(report).getByText(/weak areas/i)).toBeInTheDocument();
    expect(within(report).getByText("Hash tables")).toBeInTheDocument();
    // The report explains why a topic was flagged, rather than just naming it.
    expect(screen.getByText(/averaged below the pass mark/i)).toBeInTheDocument();
  });

  it("says plainly when an interview ended with nothing answered", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({
        status: "completed",
        overall_score: null,
        turns: [],
        completed_at: "2026-01-01T00:05:00Z",
      }),
    );

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText(/nothing to score/i)).toBeInTheDocument();
  });

  it("offers a fresh interview once one has finished", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({
        status: "completed",
        overall_score: 80,
        completed_at: "2026-01-01T00:05:00Z",
        turns: [makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 80 })],
      }),
    );

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText(/start another interview/i)).toBeInTheDocument();
  });

  it("ends an interview on request", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());
    const end = vi.spyOn(api, "endInterview").mockResolvedValue(
      makeSession({ status: "completed", overall_score: null, completed_at: "2026-01-01T00:02:00Z" }),
    );
    const user = userEvent.setup();

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByRole("button", { name: /end interview/i });

    await user.click(screen.getByRole("button", { name: /end interview/i }));

    expect(end).toHaveBeenCalledWith("int-1");
  });

  it("shows progress through the interview", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({
        question_limit: 5,
        turns: [
          makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 70 }),
          makeTurn({ id: "turn-2", question_index: 1 }),
        ],
      }),
    );

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText("1 of 5")).toBeInTheDocument();
  });

  it("offers a way forward when an interview is left with no pending question", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(
      makeSession({
        turns: [makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 80 })],
      }),
    );
    const resume = vi
      .spyOn(api, "continueInterview")
      .mockResolvedValue(
        makeSession({
          turns: [
            makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 80 }),
            makeTurn({ id: "turn-2", question_index: 1, question: "Next one?" }),
          ],
        }),
      );
    const user = userEvent.setup();

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByRole("button", { name: /^continue$/i });

    await user.click(screen.getByRole("button", { name: /^continue$/i }));

    expect(resume).toHaveBeenCalledWith("int-1");
    expect(await screen.findByText(/next one/i)).toBeInTheDocument();
  });

  it("surfaces a submission failure without losing the transcript", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());
    vi.spyOn(api, "submitInterviewAnswer").mockRejectedValue(
      new api.ApiError(503, "Couldn't reach the AI service right now. Please try again shortly."),
    );
    const user = userEvent.setup();

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByLabelText(/your answer/i);

    await user.type(screen.getByLabelText(/your answer/i), "An answer.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/couldn't reach the ai service/i),
    );
    // The question the user was answering is still on screen.
    expect(screen.getByText(/how does a hash table achieve/i)).toBeInTheDocument();
  });

  it("clears the answer box between questions", async () => {
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession());
    vi.spyOn(api, "submitInterviewAnswer").mockResolvedValue(
      makeSession({
        turns: [
          makeTurn({ answered_at: "2026-01-01T00:01:00Z", score: 72 }),
          makeTurn({ id: "turn-2", question_index: 1, question: "What about collisions?" }),
        ],
      }),
    );
    const user = userEvent.setup();

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByLabelText(/your answer/i);

    await user.type(screen.getByLabelText(/your answer/i), "First answer.");
    await user.click(screen.getByRole("button", { name: /submit answer/i }));

    await screen.findByText(/what about collisions/i);
    expect(screen.getByLabelText(/your answer/i)).toHaveValue("");
  });
});

describe("InterviewView voice mode", () => {
  beforeEach(() => {
    vi.spyOn(api, "getScoringMetrics").mockResolvedValue(METRICS);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("does not offer voice when the server cannot transcribe", async () => {
    // Checked up front rather than failing after the user has recorded an
    // answer and found out it cannot be used.
    vi.spyOn(api, "getVoiceCapability").mockResolvedValue({
      available: false,
      backend: "local",
      detail: "Local speech to text needs faster-whisper.",
    });
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByRole("button", { name: /start interview/i });

    expect(screen.queryByText("How you answer")).not.toBeInTheDocument();
  });

  it("offers a choice of typing or speaking when transcription is available", async () => {
    vi.spyOn(api, "getVoiceCapability").mockResolvedValue(VOICE_AVAILABLE);
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByText("How you answer")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /speak/i })).toBeInTheDocument();
    // States plainly that both modes are judged identically.
    expect(screen.getByText(/both modes are scored exactly the same way/i)).toBeInTheDocument();
  });

  it("starts a voice interview when speaking is chosen", async () => {
    vi.spyOn(api, "getVoiceCapability").mockResolvedValue(VOICE_AVAILABLE);
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(null);
    const start = vi
      .spyOn(api, "startNotebookInterview")
      .mockResolvedValue(makeSession({ mode: "voice" }));
    const user = userEvent.setup();

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);
    await screen.findByRole("button", { name: /speak/i });

    await user.click(screen.getByRole("button", { name: /speak/i }));
    await user.click(screen.getByRole("button", { name: /start interview/i }));

    expect(start).toHaveBeenCalledWith(
      "nb-1",
      expect.objectContaining({ mode: "voice" }),
    );
  });

  it("shows a record button during a voice interview, alongside the answer box", async () => {
    // The text box stays: the transcript lands there for correction, and
    // typing remains available if the microphone is not cooperating.
    vi.spyOn(api, "getVoiceCapability").mockResolvedValue(VOICE_AVAILABLE);
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession({ mode: "voice" }));

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    expect(await screen.findByRole("button", { name: /record answer/i })).toBeInTheDocument();
    expect(screen.getByLabelText(/edit the transcript if needed/i)).toBeInTheDocument();
  });

  it("keeps the record button out of a typed interview", async () => {
    vi.spyOn(api, "getVoiceCapability").mockResolvedValue(VOICE_AVAILABLE);
    vi.spyOn(api, "getNotebookInterview").mockResolvedValue(makeSession({ mode: "text" }));

    render(<InterviewView notebookId="nb-1" notebookName="DSA Notes" hasDocuments />);

    await screen.findByLabelText(/your answer/i);
    expect(screen.queryByRole("button", { name: /record answer/i })).not.toBeInTheDocument();
  });
});
