import { useEffect, useRef, useState } from "react";
import { useInterview } from "../hooks/useInterview";
import {
  getScoringMetrics,
  type InterviewStartOptions,
  type InterviewTurnRecord,
  type ScoringMetricsRecord,
} from "../lib/api";

const QUESTION_LIMIT_MIN = 3;
const QUESTION_LIMIT_MAX = 20;
const QUESTION_LIMIT_PRESETS = [5, 8, 12];

const DEFAULT_OPTIONS: InterviewStartOptions = {
  mode: "text",
  question_limit: 8,
  focus: "",
};

function clampLimit(value: number): number {
  if (Number.isNaN(value)) return QUESTION_LIMIT_MIN;
  return Math.min(QUESTION_LIMIT_MAX, Math.max(QUESTION_LIMIT_MIN, Math.round(value)));
}

/** Three bands rather than a continuous gradient, so a score reads as a
 * verdict at a glance. The boundaries match the backend's own weak-answer
 * threshold (50), so the colour never disagrees with whether the agent
 * decided to probe. */
function scoreTone(score: number): { text: string; bg: string; label: string } {
  if (score >= 70) {
    return { text: "text-status-ready", bg: "bg-status-ready-subtle", label: "Strong" };
  }
  if (score >= 50) {
    return { text: "text-brand-ink", bg: "bg-brand-subtle", label: "Partial" };
  }
  return { text: "text-status-failed", bg: "bg-status-failed-subtle", label: "Weak" };
}

interface InterviewViewProps {
  notebookId: string;
  notebookName: string;
  hasDocuments: boolean;
}

export function InterviewView({ notebookId, notebookName, hasDocuments }: InterviewViewProps) {
  const {
    session,
    isLoading,
    error,
    isStarting,
    isSubmitting,
    isEnding,
    start,
    submitAnswer,
    resume,
    end,
    dismissReport,
  } = useInterview(notebookId);
  // Kept in component state so reopening setup starts from the last choices
  // rather than resetting to defaults, same as QuizView and SlidesView.
  const [lastOptions, setLastOptions] = useState<InterviewStartOptions>(DEFAULT_OPTIONS);

  const handleStart = (options: InterviewStartOptions) => {
    setLastOptions(options);
    void start(options);
  };

  const showSetup = !isLoading && !isStarting && (session === null || session.status === "completed");

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-4 py-4 sm:px-6 lg:px-12">
        <div className="mx-auto flex w-full max-w-3xl flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-lg font-semibold tracking-tight text-ink">Interview</h1>
            <p className="mt-0.5 text-xs text-ink-muted">
              A mock interview on the material in "{notebookName}", which adapts to how you answer.
            </p>
          </div>
          {session?.status === "in_progress" && (
            <div className="flex shrink-0 items-center gap-3">
              <p className="text-xs text-ink-muted" aria-live="polite">
                {session.answered_count} of {session.question_limit}
              </p>
              <button
                type="button"
                onClick={() => void end()}
                disabled={isEnding}
                className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-paper disabled:opacity-50"
              >
                {isEnding ? "Ending…" : "End interview"}
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6 lg:px-12">
        <div className="mx-auto w-full max-w-3xl">
          {isLoading ? (
            <LoadingCard label="Loading interview" />
          ) : !hasDocuments ? (
            <NoDocumentsState />
          ) : (
            <>
              {error && (
                <div className="mb-4 rounded-xl border border-line bg-status-failed-subtle p-4">
                  <p role="alert" className="text-sm text-status-failed">
                    {error}
                  </p>
                  {session?.status === "in_progress" && session.current_question === null && (
                    <button
                      type="button"
                      onClick={() => void resume()}
                      disabled={isSubmitting}
                      className="mt-3 rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-paper disabled:opacity-50"
                    >
                      {isSubmitting ? "Retrying…" : "Try the next question again"}
                    </button>
                  )}
                </div>
              )}

              {session?.status === "completed" && <InterviewReport session={session} />}

              {session !== null && session.turns.length > 0 && (
                <Transcript turns={session.turns} />
              )}

              {session?.status === "in_progress" && (
                <>
                  {session.current_question !== null ? (
                    <AnswerForm
                      question={session.current_question}
                      questionNumber={session.answered_count + 1}
                      questionLimit={session.question_limit}
                      isSubmitting={isSubmitting}
                      onSubmit={(answer) => void submitAnswer(answer)}
                    />
                  ) : (
                    !error && (
                      <div className="rounded-xl border border-line bg-surface p-5">
                        <p className="text-sm font-medium text-ink">Answer recorded</p>
                        <p className="mt-1 text-xs text-ink-muted">
                          The next question has not been written yet.
                        </p>
                        <button
                          type="button"
                          onClick={() => void resume()}
                          disabled={isSubmitting}
                          className="mt-4 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
                        >
                          {isSubmitting ? "Thinking…" : "Continue"}
                        </button>
                      </div>
                    )
                  )}
                </>
              )}

              {isStarting && <LoadingCard label="Writing your first question" />}

              {showSetup && (
                <div className={session === null ? "" : "mt-6"}>
                  <SetupForm
                    initial={lastOptions}
                    isStarting={isStarting}
                    hasPreviousRun={session !== null}
                    onStart={handleStart}
                    onDismiss={dismissReport}
                  />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function NoDocumentsState() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <p className="text-sm font-medium text-ink">No documents yet</p>
      <p className="max-w-sm text-sm text-ink-muted">
        Upload a document in the Documents tab first. An interview needs material to ask you about.
      </p>
    </div>
  );
}

function LoadingCard({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="rounded-xl border border-line bg-surface p-5">
      <p className="text-sm font-medium text-ink">{label}…</p>
      <p className="mt-1 text-xs text-ink-muted">Reading your material to find something to ask.</p>
      <div className="mt-5 space-y-2.5">
        {[0, 1, 2].map((index) => (
          <div key={index} className="animate-pulse rounded-lg border border-line bg-paper p-3">
            <div className="h-2.5 w-2/3 rounded bg-line" />
            <div className="mt-2 h-2 w-full rounded bg-line" />
          </div>
        ))}
      </div>
    </div>
  );
}

function SetupForm({
  initial,
  isStarting,
  hasPreviousRun,
  onStart,
  onDismiss,
}: {
  initial: InterviewStartOptions;
  isStarting: boolean;
  hasPreviousRun: boolean;
  onStart: (options: InterviewStartOptions) => void;
  onDismiss: () => void;
}) {
  const [questionLimit, setQuestionLimit] = useState(initial.question_limit);
  const [focus, setFocus] = useState(initial.focus ?? "");
  const [metrics, setMetrics] = useState<ScoringMetricsRecord | null>(null);

  useEffect(() => {
    // Best-effort: the setup form works fine without it, so a failure here is
    // swallowed rather than shown as an error on a screen that is otherwise
    // working.
    let active = true;
    void getScoringMetrics()
      .then((record) => {
        if (active) setMetrics(record);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    onStart({
      mode: "text",
      question_limit: clampLimit(questionLimit),
      focus: focus.trim() || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-ink">
        {hasPreviousRun ? "Start another interview" : "Set up your interview"}
      </h2>
      <p className="mt-1 text-xs text-ink-muted">
        Questions come from this notebook's material. Each answer is scored, and a weak answer gets
        a follow-up on the same topic before the interview moves on.
      </p>

      <div className="mt-5">
        <label htmlFor="question-limit" className="text-xs font-medium text-ink-muted">
          Maximum questions
        </label>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setQuestionLimit((n) => clampLimit(n - 1))}
              disabled={questionLimit <= QUESTION_LIMIT_MIN}
              aria-label="Decrease question limit"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line text-ink transition-colors hover:bg-paper disabled:opacity-40"
            >
              <MinusIcon />
            </button>
            <input
              id="question-limit"
              type="number"
              inputMode="numeric"
              min={QUESTION_LIMIT_MIN}
              max={QUESTION_LIMIT_MAX}
              value={questionLimit}
              onChange={(event) => setQuestionLimit(Number(event.target.value))}
              onBlur={() => setQuestionLimit((n) => clampLimit(n))}
              className="h-9 w-16 rounded-lg border border-line text-center text-sm text-ink focus:border-brand focus:outline-none"
            />
            <button
              type="button"
              onClick={() => setQuestionLimit((n) => clampLimit(n + 1))}
              disabled={questionLimit >= QUESTION_LIMIT_MAX}
              aria-label="Increase question limit"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line text-ink transition-colors hover:bg-paper disabled:opacity-40"
            >
              <PlusIcon />
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {QUESTION_LIMIT_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setQuestionLimit(preset)}
                aria-pressed={questionLimit === preset}
                className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
                  questionLimit === preset
                    ? "border-brand bg-brand-subtle text-brand-ink"
                    : "border-line text-ink-muted hover:bg-paper"
                }`}
              >
                {preset}
              </button>
            ))}
          </div>
        </div>
        <p className="mt-2 text-xs text-ink-faint">
          The interview can finish sooner if it covers every topic in your material.
        </p>
      </div>

      <div className="mt-5">
        <label htmlFor="interview-focus" className="text-xs font-medium text-ink-muted">
          Focus on (optional)
        </label>
        <input
          id="interview-focus"
          type="text"
          value={focus}
          onChange={(event) => setFocus(event.target.value)}
          maxLength={200}
          placeholder="e.g. the networking chapter, system design"
          className="mt-1 w-full rounded-lg border border-line px-3 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
        />
      </div>

      {metrics !== null && <ScoringNote metrics={metrics} />}

      <div className="mt-5 flex flex-col gap-2 sm:flex-row">
        <button
          type="submit"
          disabled={isStarting}
          className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50 sm:w-auto"
        >
          {isStarting ? "Starting…" : "Start interview"}
        </button>
        {hasPreviousRun && (
          <button
            type="button"
            onClick={onDismiss}
            className="w-full rounded-lg border border-line px-4 py-2.5 text-sm font-medium text-ink transition-colors hover:bg-paper sm:w-auto"
          >
            Hide previous report
          </button>
        )}
      </div>
    </form>
  );
}

/** States how answers are scored, including the model's held-out error.
 * Deliberately specific rather than reassuring: a number the user can judge
 * is worth more than a claim that the scoring is accurate. */
function ScoringNote({ metrics }: { metrics: ScoringMetricsRecord }) {
  return (
    <div className="mt-5 rounded-lg bg-paper px-3 py-2.5">
      <p className="text-xs leading-relaxed text-ink-muted">
        {metrics.using_fallback ? (
          <>
            Answers are scored by a rule based fallback, because no trained scoring model was found
            in this install. Scores stay consistent and explainable, but are less well calibrated
            than the trained model.
          </>
        ) : (
          <>
            Answers are scored by a trained model over five measured features, not by an AI's
            opinion, so the same answer always scores the same.{" "}
            {metrics.held_out_mae !== null && (
              <>
                On held out data it is off by {metrics.held_out_mae} points out of 100 on average.
              </>
            )}
          </>
        )}
      </p>
    </div>
  );
}

function Transcript({ turns }: { turns: InterviewTurnRecord[] }) {
  return (
    <ol className="mb-6 space-y-4">
      {turns
        .filter((turn) => turn.answered_at !== null)
        .map((turn) => (
          <li key={turn.id}>
            <AnsweredTurn turn={turn} />
          </li>
        ))}
    </ol>
  );
}

function AnsweredTurn({ turn }: { turn: InterviewTurnRecord }) {
  const [showDetail, setShowDetail] = useState(false);
  const tone = turn.score === null ? null : scoreTone(turn.score);

  return (
    <article className="rounded-xl border border-line bg-surface p-4 sm:p-5">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] font-medium tracking-wider text-ink-faint uppercase">
              Question {turn.question_index + 1}
            </span>
            {turn.topic !== null && (
              <span className="truncate rounded-full bg-paper px-2 py-0.5 text-[11px] text-ink-muted">
                {turn.topic}
              </span>
            )}
            {turn.is_probe && (
              // Surfaced rather than hidden: this badge is the visible proof
              // that the interview responded to the previous answer instead
              // of reading from a list.
              <span className="rounded-full bg-brand-subtle px-2 py-0.5 text-[11px] font-medium text-brand-ink">
                Follow up
              </span>
            )}
          </div>
          <h3 className="mt-1.5 text-sm font-medium text-ink">{turn.question}</h3>
        </div>
        {tone !== null && turn.score !== null && (
          <span
            className={`shrink-0 rounded-lg px-2.5 py-1 text-sm font-semibold ${tone.bg} ${tone.text}`}
          >
            {turn.score}
            <span className="ml-0.5 text-[11px] font-medium">/100</span>
          </span>
        )}
      </header>

      {turn.answer_text !== null && (
        <div className="mt-3 rounded-lg bg-paper px-3 py-2.5">
          <p className="text-[11px] font-medium tracking-wider text-ink-faint uppercase">
            Your answer
          </p>
          <p className="mt-1 text-sm whitespace-pre-wrap text-ink">
            {turn.answer_text.trim() || "You skipped this question."}
          </p>
        </div>
      )}

      {turn.feedback !== null && <p className="mt-3 text-sm text-ink-muted">{turn.feedback}</p>}

      {turn.missed_points.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-medium tracking-wider text-ink-faint uppercase">
            Not mentioned
          </p>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">
            {turn.missed_points.map((point) => (
              <li
                key={point}
                className="rounded-full bg-status-failed-subtle px-2 py-0.5 text-xs text-status-failed"
              >
                {point}
              </li>
            ))}
          </ul>
        </div>
      )}

      <button
        type="button"
        onClick={() => setShowDetail((open) => !open)}
        aria-expanded={showDetail}
        className="mt-3 text-xs font-medium text-ink-muted underline-offset-2 transition-colors hover:text-ink hover:underline"
      >
        {showDetail ? "Hide model answer and score breakdown" : "Show model answer and score breakdown"}
      </button>

      {showDetail && (
        <div className="mt-3 space-y-3 border-t border-line pt-3">
          {turn.ideal_answer !== null && (
            <div>
              <p className="text-[11px] font-medium tracking-wider text-ink-faint uppercase">
                Answer from your material
              </p>
              <p className="mt-1 text-sm text-ink">{turn.ideal_answer}</p>
            </div>
          )}
          {Object.keys(turn.features).length > 0 && <FeatureBreakdown features={turn.features} />}
        </div>
      )}
    </article>
  );
}

const FEATURE_LABELS: Record<string, string> = {
  semantic_similarity: "Closeness to the model answer",
  concept_coverage: "Key points covered",
  length_ratio: "Length vs the model answer",
  filler_ratio: "Filler words",
  non_answer: "Counted as no answer",
};

/** The reason a trained model over named features was chosen over asking an
 * LLM for a verdict: the score can be taken apart and shown. */
function FeatureBreakdown({ features }: { features: Record<string, number> }) {
  const rows = Object.entries(features).filter(([key]) => key in FEATURE_LABELS);
  if (rows.length === 0) return null;

  return (
    <div>
      <p className="text-[11px] font-medium tracking-wider text-ink-faint uppercase">
        How this score was measured
      </p>
      <dl className="mt-2 space-y-1.5">
        {rows.map(([key, value]) => (
          <div key={key} className="flex items-center gap-3">
            <dt className="w-44 shrink-0 text-xs text-ink-muted">{FEATURE_LABELS[key]}</dt>
            <dd className="flex min-w-0 flex-1 items-center gap-2">
              <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full bg-brand"
                  style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }}
                />
              </div>
              <span className="w-10 shrink-0 text-right text-xs tabular-nums text-ink-muted">
                {value.toFixed(2)}
              </span>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function AnswerForm({
  question,
  questionNumber,
  questionLimit,
  isSubmitting,
  onSubmit,
}: {
  question: InterviewTurnRecord;
  questionNumber: number;
  questionLimit: number;
  isSubmitting: boolean;
  onSubmit: (answer: string) => void;
}) {
  const [answer, setAnswer] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // A new question means a new empty box, and focus moved to it so answering
  // several questions in a row never needs the mouse. Keyed on the turn id so
  // this fires per question rather than on every keystroke.
  useEffect(() => {
    setAnswer("");
    textareaRef.current?.focus();
  }, [question.id]);

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    if (isSubmitting) return;
    onSubmit(answer);
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-brand bg-surface p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium tracking-wider text-brand-ink uppercase">
          Question {questionNumber} of {questionLimit}
        </span>
        {question.topic !== null && (
          <span className="truncate rounded-full bg-paper px-2 py-0.5 text-[11px] text-ink-muted">
            {question.topic}
          </span>
        )}
        {question.is_probe && (
          <span className="rounded-full bg-brand-subtle px-2 py-0.5 text-[11px] font-medium text-brand-ink">
            Follow up
          </span>
        )}
      </div>

      <h2 className="mt-2 text-base font-medium text-ink">{question.question}</h2>

      <label htmlFor="interview-answer" className="mt-4 block text-xs font-medium text-ink-muted">
        Your answer
      </label>
      <textarea
        id="interview-answer"
        ref={textareaRef}
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        maxLength={5000}
        rows={6}
        disabled={isSubmitting}
        placeholder="Answer in your own words, as you would out loud."
        className="mt-1 w-full resize-y rounded-lg border border-line px-3 py-2.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none disabled:opacity-60"
      />

      <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-xs text-ink-faint">
          {answer.trim().length === 0
            ? "Submitting an empty answer counts as skipping this question."
            : `${answer.trim().split(/\s+/).length} words`}
        </p>
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50 sm:w-auto"
        >
          {isSubmitting ? "Scoring your answer…" : "Submit answer"}
        </button>
      </div>
    </form>
  );
}

function InterviewReport({
  session,
}: {
  session: {
    overall_score: number | null;
    weak_areas: string[];
    answered_count: number;
    question_limit: number;
    turns: InterviewTurnRecord[];
  };
}) {
  const tone = session.overall_score === null ? null : scoreTone(session.overall_score);
  const answered = session.turns.filter((turn) => turn.score !== null);

  return (
    <section
      aria-labelledby="interview-report-heading"
      className="mb-6 rounded-xl border border-line bg-surface p-4 sm:p-5"
    >
      <h2 id="interview-report-heading" className="text-sm font-semibold text-ink">
        Interview report
      </h2>

      {session.overall_score === null ? (
        <p className="mt-2 text-sm text-ink-muted">
          This interview ended before any question was answered, so there is nothing to score.
        </p>
      ) : (
        <>
          <div className="mt-4 flex flex-wrap items-end gap-4">
            <div>
              <p className={`text-3xl font-semibold tabular-nums ${tone?.text}`}>
                {session.overall_score}
                <span className="ml-1 text-base font-medium text-ink-faint">/100</span>
              </p>
              <p className="mt-0.5 text-xs text-ink-muted">
                Average across {answered.length} answered{" "}
                {answered.length === 1 ? "question" : "questions"}
              </p>
            </div>
            {tone !== null && (
              <span
                className={`rounded-full px-2.5 py-1 text-xs font-medium ${tone.bg} ${tone.text}`}
              >
                {tone.label}
              </span>
            )}
          </div>

          <div className="mt-4 border-t border-line pt-4">
            <p className="text-[11px] font-medium tracking-wider text-ink-faint uppercase">
              Weak areas
            </p>
            {session.weak_areas.length === 0 ? (
              <p className="mt-1.5 text-sm text-ink-muted">
                No topic averaged below the pass mark. Nothing flagged.
              </p>
            ) : (
              <>
                <ul className="mt-1.5 flex flex-wrap gap-1.5">
                  {session.weak_areas.map((area) => (
                    <li
                      key={area}
                      className="rounded-full bg-status-failed-subtle px-2.5 py-1 text-xs text-status-failed"
                    >
                      {area}
                    </li>
                  ))}
                </ul>
                <p className="mt-2 text-xs text-ink-faint">
                  Flagged because your answers on these topics averaged below the pass mark, not
                  because of a single weak answer.
                </p>
              </>
            )}
          </div>
        </>
      )}
    </section>
  );
}

function MinusIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      className="h-3.5 w-3.5"
    >
      <path strokeLinecap="round" d="M5 12h14" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      className="h-3.5 w-3.5"
    >
      <path strokeLinecap="round" d="M12 5v14M5 12h14" />
    </svg>
  );
}
