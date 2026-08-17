import { useState } from "react";
import { useQuiz } from "../hooks/useQuiz";
import type { QuizDifficulty, QuizGenerateOptions } from "../lib/api";
import { describeErrorReason } from "../lib/errorMessages";

const DEFAULT_OPTIONS: QuizGenerateOptions = {
  question_count: 8,
  difficulty: "mixed",
  allow_general_knowledge: false,
  focus: "",
};

interface QuizViewProps {
  notebookId: string;
  notebookName: string;
  hasDocuments: boolean;
}

export function QuizView({ notebookId, notebookName, hasDocuments }: QuizViewProps) {
  const { quiz, isLoading, error, isGenerating, generate } = useQuiz(notebookId);
  // Neither of these is persisted server-side (generation params aren't part
  // of the Quiz record, and shuffling is purely a display concern) — kept
  // here only so reopening setup ("New questions") starts from what you
  // picked last time instead of resetting to defaults.
  const [lastOptions, setLastOptions] = useState<QuizGenerateOptions>(DEFAULT_OPTIONS);
  const [shuffle, setShuffle] = useState(false);
  // Setup is shown before the very first generation, and again whenever the
  // user explicitly asks to reconfigure — never re-shown just because a poll
  // tick re-ran, so it can't clobber an in-progress or completed attempt.
  const [isConfiguring, setIsConfiguring] = useState(false);

  const handleGenerate = (options: QuizGenerateOptions, shuffleOrder: boolean) => {
    setLastOptions(options);
    setShuffle(shuffleOrder);
    setIsConfiguring(false);
    void generate(options);
  };

  // isGenerating excluded here so a click on "Generate" can't re-show setup
  // during the gap between the call starting and `quiz` updating from it —
  // without this, quiz===null (still true in that gap, pre-first-generation)
  // would flash the form again right after submitting it.
  const showSetup = !isLoading && !error && !isGenerating && (quiz === null || isConfiguring);
  const isBusy = isGenerating || quiz?.status === "pending" || quiz?.status === "generating";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-6 py-4 lg:px-12">
        <h1 className="text-lg font-semibold tracking-tight text-ink">Quiz</h1>
        <p className="mt-0.5 text-xs text-ink-muted">
          Test yourself on the documents in "{notebookName}".
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 lg:px-12">
        <div className="mx-auto w-full max-w-3xl">
          {isLoading ? (
            <QuizSkeleton label="Loading quiz" />
          ) : error ? (
            <ErrorState message={error} onRetry={() => void generate(lastOptions)} isRetrying={isGenerating} />
          ) : !hasDocuments ? (
            <NoDocumentsState />
          ) : showSetup ? (
            <QuizSetupForm
              initial={lastOptions}
              initialShuffle={shuffle}
              isGenerating={isGenerating}
              onGenerate={handleGenerate}
            />
          ) : isBusy ? (
            <QuizSkeleton label="Generating quiz" />
          ) : quiz?.status === "failed" ? (
            <ErrorState
              message={describeErrorReason(quiz.error_reason)}
              onRetry={() => setIsConfiguring(true)}
              isRetrying={isGenerating}
            />
          ) : quiz ? (
            <QuizTaker
              key={quiz.id}
              questions={quiz.questions}
              shuffle={shuffle}
              onReconfigure={() => setIsConfiguring(true)}
            />
          ) : null}
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
        Upload a document in the Documents tab first — a quiz needs something to be about.
      </p>
    </div>
  );
}

function ErrorState({
  message,
  onRetry,
  isRetrying,
}: {
  message: string;
  onRetry: () => void;
  isRetrying: boolean;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <p role="alert" className="text-sm text-status-failed">
        {message}
      </p>
      <button
        type="button"
        onClick={onRetry}
        disabled={isRetrying}
        className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-paper disabled:opacity-50"
      >
        {isRetrying ? "Retrying…" : "Try again"}
      </button>
    </div>
  );
}

const DIFFICULTY_OPTIONS: { value: QuizDifficulty; label: string; description: string; bars: number }[] = [
  { value: "easy", label: "Easy", description: "Straightforward recall of stated facts.", bars: 1 },
  { value: "medium", label: "Medium", description: "Some connecting of related ideas.", bars: 2 },
  { value: "hard", label: "Hard", description: "Reasoning, comparisons, applying concepts.", bars: 3 },
  { value: "mixed", label: "Mixed", description: "A blend of all difficulty levels.", bars: 0 },
];

const QUESTION_COUNT_MIN = 3;
const QUESTION_COUNT_MAX = 20;
const QUESTION_COUNT_PRESETS = [5, 8, 10, 15, 20];

function clampCount(value: number): number {
  if (Number.isNaN(value)) return QUESTION_COUNT_MIN;
  return Math.min(QUESTION_COUNT_MAX, Math.max(QUESTION_COUNT_MIN, Math.round(value)));
}

function QuizSetupForm({
  initial,
  initialShuffle,
  isGenerating,
  onGenerate,
}: {
  initial: QuizGenerateOptions;
  initialShuffle: boolean;
  isGenerating: boolean;
  onGenerate: (options: QuizGenerateOptions, shuffle: boolean) => void;
}) {
  const [questionCount, setQuestionCount] = useState(initial.question_count);
  const [difficulty, setDifficulty] = useState<QuizDifficulty>(initial.difficulty);
  const [allowGeneralKnowledge, setAllowGeneralKnowledge] = useState(initial.allow_general_knowledge);
  const [shuffle, setShuffle] = useState(initialShuffle);
  const [focus, setFocus] = useState(initial.focus ?? "");

  const difficultyLabel = DIFFICULTY_OPTIONS.find((d) => d.value === difficulty)?.label ?? "mixed";
  const summary = [
    `Generates ${questionCount} ${difficultyLabel.toLowerCase()}-difficulty question${questionCount === 1 ? "" : "s"}`,
    allowGeneralKnowledge ? "from your material, filling gaps with general knowledge" : "strictly from your material",
    focus.trim() ? `, focused on "${focus.trim()}"` : "",
    ".",
  ].join(" ");

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    onGenerate(
      {
        question_count: clampCount(questionCount),
        difficulty,
        allow_general_knowledge: allowGeneralKnowledge,
        focus: focus.trim() || undefined,
      },
      shuffle,
    );
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-ink">Set up your quiz</h2>
      <p className="mt-1 text-xs text-ink-muted">
        Customize what gets generated from this notebook's material.
      </p>

      <div className="mt-5">
        <label htmlFor="quiz-question-count" className="text-xs font-medium text-ink-muted">
          Number of questions
        </label>
        <div className="mt-2 flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setQuestionCount((n) => clampCount(n - 1))}
              disabled={questionCount <= QUESTION_COUNT_MIN}
              aria-label="Decrease question count"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line text-ink transition-colors hover:bg-paper disabled:opacity-40"
            >
              <MinusIcon />
            </button>
            <input
              id="quiz-question-count"
              type="number"
              min={QUESTION_COUNT_MIN}
              max={QUESTION_COUNT_MAX}
              value={questionCount}
              onChange={(event) => setQuestionCount(Number(event.target.value))}
              onBlur={() => setQuestionCount((n) => clampCount(n))}
              className="h-8 w-14 rounded-lg border border-line text-center text-sm text-ink focus:border-brand focus:outline-none"
            />
            <button
              type="button"
              onClick={() => setQuestionCount((n) => clampCount(n + 1))}
              disabled={questionCount >= QUESTION_COUNT_MAX}
              aria-label="Increase question count"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line text-ink transition-colors hover:bg-paper disabled:opacity-40"
            >
              <PlusIcon />
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {QUESTION_COUNT_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setQuestionCount(preset)}
                aria-pressed={questionCount === preset}
                className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                  questionCount === preset
                    ? "border-brand bg-brand-subtle text-brand-ink"
                    : "border-line text-ink-muted hover:bg-paper"
                }`}
              >
                {preset}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-5">
        <p className="text-xs font-medium text-ink-muted">Difficulty</p>
        <div className="mt-2 grid grid-cols-2 gap-2">
          {DIFFICULTY_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setDifficulty(option.value)}
              aria-pressed={difficulty === option.value}
              className={`rounded-lg border p-2.5 text-left transition-colors ${
                difficulty === option.value ? "border-brand bg-brand-subtle" : "border-line hover:bg-paper"
              }`}
            >
              <span className="flex items-center gap-1.5">
                <DifficultyIcon bars={option.bars} />
                <span className="text-sm font-medium text-ink">{option.label}</span>
              </span>
              <p className="mt-0.5 text-xs text-ink-muted">{option.description}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5">
        <label htmlFor="quiz-focus" className="text-xs font-medium text-ink-muted">
          Focus on (optional)
        </label>
        <input
          id="quiz-focus"
          type="text"
          value={focus}
          onChange={(event) => setFocus(event.target.value)}
          maxLength={200}
          placeholder="e.g. chapter 3, testing strategies"
          className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
        />
      </div>

      <div className="mt-5 space-y-2">
        <ToggleSwitch
          checked={allowGeneralKnowledge}
          onChange={setAllowGeneralKnowledge}
          label="Allow general knowledge"
          description="Let the AI fill gaps where your material is thin, instead of staying strictly within what you've uploaded."
        />
        <ToggleSwitch
          checked={shuffle}
          onChange={setShuffle}
          label="Shuffle question order"
          description="Show questions in a random order each time you take this quiz."
        />
      </div>

      <p className="mt-4 rounded-lg bg-paper px-3 py-2 text-xs leading-relaxed text-ink-muted">{summary}</p>

      <button
        type="submit"
        disabled={isGenerating}
        className="mt-4 w-full rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
      >
        {isGenerating ? "Generating…" : "Generate quiz"}
      </button>
    </form>
  );
}

function ToggleSwitch({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  description: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-start justify-between gap-3 rounded-lg border border-line p-3 text-left transition-colors hover:bg-paper"
    >
      <span>
        <span className="block text-sm font-medium text-ink">{label}</span>
        <span className="mt-0.5 block text-xs text-ink-muted">{description}</span>
      </span>
      <span
        className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${
          checked ? "bg-brand" : "bg-line-strong"
        }`}
      >
        <span
          className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
            checked ? "translate-x-4" : "translate-x-0"
          }`}
        />
      </span>
    </button>
  );
}

function DifficultyIcon({ bars }: { bars: number }) {
  if (bars === 0) {
    return (
      <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="h-3.5 w-3.5 text-ink-faint">
        <path strokeLinecap="round" strokeLinejoin="round" d="M17 3 21 7l-4 4M7 21 3 17l4-4M21 7H8a4 4 0 0 0-4 4M3 17h13a4 4 0 0 0 4-4" />
      </svg>
    );
  }
  return (
    <span className="flex items-end gap-0.5" aria-hidden="true">
      {[1, 2, 3].map((bar) => (
        <span
          key={bar}
          className={`w-1 rounded-sm ${bar <= bars ? "bg-brand" : "bg-line"}`}
          style={{ height: `${4 + bar * 2}px` }}
        />
      ))}
    </span>
  );
}

function MinusIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-3.5 w-3.5">
      <path strokeLinecap="round" d="M5 12h14" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-3.5 w-3.5">
      <path strokeLinecap="round" d="M12 5v14M5 12h14" />
    </svg>
  );
}

interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

function shuffledIndices(count: number): number[] {
  const indices = Array.from({ length: count }, (_, i) => i);
  for (let i = indices.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [indices[i], indices[j]] = [indices[j], indices[i]];
  }
  return indices;
}

function QuizTaker({
  questions,
  shuffle,
  onReconfigure,
}: {
  questions: QuizQuestion[];
  shuffle: boolean;
  onReconfigure: () => void;
}) {
  // Order is computed once per mount (this component remounts on every new
  // quiz via `key={quiz.id}` in QuizView, and Retake doesn't remount it —
  // reshuffling on Retake would be a different, also-reasonable quiz-app
  // behavior, but keeping the order stable across a retake of the *same*
  // quiz is less surprising). Indexes into `questions`, not display
  // positions, so scoring/selection state stays keyed by the original
  // (stable) question identity regardless of display order.
  const [order] = useState(() => (shuffle ? shuffledIndices(questions.length) : questions.map((_, i) => i)));

  // Two-step per question: `selections` is just the highlighted choice,
  // `submitted` is what actually got confirmed and graded — matches a real
  // quiz app (pick an answer, change your mind if you want, then commit)
  // rather than grading the instant you click an option.
  const [selections, setSelections] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState<Record<number, boolean>>({});

  const submittedCount = Object.keys(submitted).length;
  const allSubmitted = submittedCount === questions.length;
  const score = questions.reduce(
    (total, q, i) => total + (submitted[i] && selections[i] === q.correct_index ? 1 : 0),
    0,
  );

  const selectOption = (questionIndex: number, optionIndex: number) => {
    if (submitted[questionIndex]) return;
    setSelections((prev) => ({ ...prev, [questionIndex]: optionIndex }));
  };

  const submitAnswer = (questionIndex: number) => {
    if (selections[questionIndex] === undefined) return;
    setSubmitted((prev) => ({ ...prev, [questionIndex]: true }));
  };

  const retake = () => {
    setSelections({});
    setSubmitted({});
  };

  return (
    <div className="pb-10">
      <div className="sticky top-0 z-10 mb-4 rounded-xl border border-line bg-surface px-4 py-3 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-ink">
            {allSubmitted ? "Quiz complete" : `${submittedCount} of ${questions.length} answered`}
          </span>
          {submittedCount > 0 && (
            <span
              className={`text-sm font-semibold ${allSubmitted ? "text-status-ready" : "text-ink-muted"}`}
            >
              {allSubmitted
                ? `${score} / ${questions.length} correct`
                : `${score} / ${submittedCount} correct so far`}
            </span>
          )}
        </div>
        {submittedCount > 0 && (
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-brand transition-[width] duration-300"
              style={{ width: `${(submittedCount / questions.length) * 100}%` }}
            />
          </div>
        )}
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={retake}
            disabled={submittedCount === 0}
            className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-paper disabled:opacity-50"
          >
            Retake
          </button>
          <button
            type="button"
            onClick={onReconfigure}
            className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:bg-paper hover:text-ink"
          >
            New questions
          </button>
        </div>
      </div>

      <ol className="space-y-6">
        {order.map((questionIndex, displayPosition) => {
          const q = questions[questionIndex];
          const isSubmitted = submitted[questionIndex] ?? false;
          const hasSelection = selections[questionIndex] !== undefined;
          return (
            <li key={questionIndex} className="rounded-xl border border-line bg-surface p-4">
              <p className="text-sm font-medium text-ink">{`${displayPosition + 1}. ${q.question}`}</p>
              <div
                role="radiogroup"
                aria-label={`Question ${displayPosition + 1} options`}
                className="mt-3 space-y-2"
              >
                {q.options.map((option, optionIndex) => (
                  <QuizOption
                    key={optionIndex}
                    option={option}
                    isSelected={selections[questionIndex] === optionIndex}
                    isCorrect={optionIndex === q.correct_index}
                    revealed={isSubmitted}
                    onSelect={() => selectOption(questionIndex, optionIndex)}
                  />
                ))}
              </div>
              {isSubmitted ? (
                <p className="mt-3 text-xs leading-relaxed text-ink-muted">{q.explanation}</p>
              ) : (
                <div className="mt-3 flex justify-end">
                  <button
                    type="button"
                    onClick={() => submitAnswer(questionIndex)}
                    disabled={!hasSelection}
                    className="rounded-lg bg-brand px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
                  >
                    Submit answer
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function QuizOption({
  option,
  isSelected,
  isCorrect,
  revealed,
  onSelect,
}: {
  option: string;
  isSelected: boolean;
  isCorrect: boolean;
  revealed: boolean;
  onSelect: () => void;
}) {
  let className =
    "flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors ";
  if (revealed) {
    if (isCorrect) {
      className += "border-status-ready bg-status-ready-subtle text-ink";
    } else if (isSelected) {
      className += "border-status-failed bg-status-failed-subtle text-ink";
    } else {
      className += "border-line text-ink-muted";
    }
  } else if (isSelected) {
    className += "border-brand bg-brand-subtle text-brand-ink";
  } else {
    className += "border-line text-ink hover:bg-paper";
  }

  return (
    <button
      type="button"
      role="radio"
      aria-checked={isSelected}
      onClick={onSelect}
      disabled={revealed}
      className={className}
    >
      <span
        className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${
          isSelected ? "border-brand" : "border-line-strong"
        }`}
      >
        {isSelected && <span className="h-2 w-2 rounded-full bg-brand" />}
      </span>
      {option}
    </button>
  );
}

function QuizSkeleton({ label }: { label: string }) {
  return (
    <div className="space-y-4" aria-busy="true" aria-label={label}>
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i} className="space-y-2 rounded-xl border border-line bg-surface p-4">
          <div className="h-3 w-3/4 animate-pulse rounded bg-line" />
          <div className="h-8 w-full animate-pulse rounded bg-line/60" />
          <div className="h-8 w-full animate-pulse rounded bg-line/60" />
        </div>
      ))}
    </div>
  );
}
