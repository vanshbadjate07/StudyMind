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
  // Not persisted server-side (generation params aren't part of the Quiz
  // record) — kept here purely so reopening setup ("New questions") starts
  // from what you picked last time instead of resetting to defaults.
  const [lastOptions, setLastOptions] = useState<QuizGenerateOptions>(DEFAULT_OPTIONS);
  // Setup is shown before the very first generation, and again whenever the
  // user explicitly asks to reconfigure — never re-shown just because a poll
  // tick re-ran, so it can't clobber an in-progress or completed attempt.
  const [isConfiguring, setIsConfiguring] = useState(false);

  const handleGenerate = (options: QuizGenerateOptions) => {
    setLastOptions(options);
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
            <QuizSetupForm initial={lastOptions} isGenerating={isGenerating} onGenerate={handleGenerate} />
          ) : isBusy ? (
            <QuizSkeleton label="Generating quiz" />
          ) : quiz?.status === "failed" ? (
            <ErrorState
              message={describeErrorReason(quiz.error_reason)}
              onRetry={() => setIsConfiguring(true)}
              isRetrying={isGenerating}
            />
          ) : quiz ? (
            <QuizTaker key={quiz.id} questions={quiz.questions} onReconfigure={() => setIsConfiguring(true)} />
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

const DIFFICULTY_OPTIONS: { value: QuizDifficulty; label: string; description: string }[] = [
  { value: "easy", label: "Easy", description: "Straightforward recall of stated facts." },
  { value: "medium", label: "Medium", description: "Some connecting of related ideas." },
  { value: "hard", label: "Hard", description: "Reasoning, comparisons, applying concepts." },
  { value: "mixed", label: "Mixed", description: "A blend of all difficulty levels." },
];

const QUESTION_COUNT_MIN = 3;
const QUESTION_COUNT_MAX = 20;

function QuizSetupForm({
  initial,
  isGenerating,
  onGenerate,
}: {
  initial: QuizGenerateOptions;
  isGenerating: boolean;
  onGenerate: (options: QuizGenerateOptions) => void;
}) {
  const [questionCount, setQuestionCount] = useState(initial.question_count);
  const [difficulty, setDifficulty] = useState<QuizDifficulty>(initial.difficulty);
  const [allowGeneralKnowledge, setAllowGeneralKnowledge] = useState(initial.allow_general_knowledge);
  const [focus, setFocus] = useState(initial.focus ?? "");

  const clampedCount = Math.min(QUESTION_COUNT_MAX, Math.max(QUESTION_COUNT_MIN, questionCount || QUESTION_COUNT_MIN));

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    onGenerate({
      question_count: clampedCount,
      difficulty,
      allow_general_knowledge: allowGeneralKnowledge,
      focus: focus.trim() || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-ink">Set up your quiz</h2>
      <p className="mt-1 text-xs text-ink-muted">
        Customize what gets generated from this notebook's material.
      </p>

      <div className="mt-4">
        <label htmlFor="quiz-question-count" className="text-xs font-medium text-ink-muted">
          Number of questions
        </label>
        <input
          id="quiz-question-count"
          type="number"
          min={QUESTION_COUNT_MIN}
          max={QUESTION_COUNT_MAX}
          value={questionCount}
          onChange={(event) => setQuestionCount(Number(event.target.value))}
          onBlur={() => setQuestionCount(clampedCount)}
          className="mt-1 w-24 rounded-lg border border-line px-3 py-1.5 text-sm text-ink focus:border-brand focus:outline-none"
        />
        <span className="ml-2 text-xs text-ink-faint">
          ({QUESTION_COUNT_MIN}-{QUESTION_COUNT_MAX})
        </span>
      </div>

      <div className="mt-4">
        <p className="text-xs font-medium text-ink-muted">Difficulty</p>
        <div className="mt-1.5 grid grid-cols-2 gap-2">
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
              <p className="text-sm font-medium text-ink">{option.label}</p>
              <p className="mt-0.5 text-xs text-ink-muted">{option.description}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4">
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

      <label className="mt-4 flex cursor-pointer items-start gap-2 text-xs text-ink-muted">
        <input
          type="checkbox"
          checked={allowGeneralKnowledge}
          onChange={(event) => setAllowGeneralKnowledge(event.target.checked)}
          className="mt-0.5 h-3.5 w-3.5 rounded border-line-strong accent-brand"
        />
        Let the AI fill gaps with general knowledge where your material is thin (otherwise every
        question is answerable strictly from what you've uploaded)
      </label>

      <button
        type="submit"
        disabled={isGenerating}
        className="mt-5 w-full rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
      >
        {isGenerating ? "Generating…" : "Generate quiz"}
      </button>
    </form>
  );
}

interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

function QuizTaker({
  questions,
  onReconfigure,
}: {
  questions: QuizQuestion[];
  onReconfigure: () => void;
}) {
  // Selecting an option *is* submitting that question — there's no separate
  // submit step, and once a question has an entry here it's locked in
  // (QuizOption disables further clicks via `revealed`).
  const [answers, setAnswers] = useState<Record<number, number>>({});

  const answeredCount = Object.keys(answers).length;
  const allAnswered = answeredCount === questions.length;
  const score = questions.reduce((total, q, i) => total + (answers[i] === q.correct_index ? 1 : 0), 0);

  const selectAnswer = (questionIndex: number, optionIndex: number) => {
    if (questionIndex in answers) return; // already locked in
    setAnswers((prev) => ({ ...prev, [questionIndex]: optionIndex }));
  };

  const retake = () => setAnswers({});

  return (
    <div className="pb-10">
      <div className="sticky top-0 z-10 mb-4 rounded-xl border border-line bg-surface px-4 py-3 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm font-medium text-ink">
            {allAnswered ? "Quiz complete" : `${answeredCount} of ${questions.length} answered`}
          </span>
          {answeredCount > 0 && (
            <span
              className={`text-sm font-semibold ${allAnswered ? "text-status-ready" : "text-ink-muted"}`}
            >
              {allAnswered
                ? `${score} / ${questions.length} correct`
                : `${score} / ${answeredCount} correct so far`}
            </span>
          )}
        </div>
        {answeredCount > 0 && (
          <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-line">
            <div
              className="h-full rounded-full bg-brand transition-[width] duration-300"
              style={{ width: `${(answeredCount / questions.length) * 100}%` }}
            />
          </div>
        )}
        <div className="mt-3 flex gap-2">
          <button
            type="button"
            onClick={retake}
            disabled={answeredCount === 0}
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
        {questions.map((q, questionIndex) => {
          const isAnswered = questionIndex in answers;
          return (
            <li key={questionIndex} className="rounded-xl border border-line bg-surface p-4">
              <p className="text-sm font-medium text-ink">{`${questionIndex + 1}. ${q.question}`}</p>
              <div
                role="radiogroup"
                aria-label={`Question ${questionIndex + 1} options`}
                className="mt-3 space-y-2"
              >
                {q.options.map((option, optionIndex) => (
                  <QuizOption
                    key={optionIndex}
                    option={option}
                    isSelected={answers[questionIndex] === optionIndex}
                    isCorrect={optionIndex === q.correct_index}
                    revealed={isAnswered}
                    onSelect={() => selectAnswer(questionIndex, optionIndex)}
                  />
                ))}
              </div>
              {isAnswered && <p className="mt-3 text-xs leading-relaxed text-ink-muted">{q.explanation}</p>}
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
