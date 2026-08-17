import { useState } from "react";
import { useQuiz } from "../hooks/useQuiz";
import { describeErrorReason } from "../lib/errorMessages";

interface QuizViewProps {
  notebookId: string;
  notebookName: string;
  hasDocuments: boolean;
}

export function QuizView({ notebookId, notebookName, hasDocuments }: QuizViewProps) {
  const { quiz, isLoading, error, isGenerating, generate } = useQuiz(notebookId);

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
            <ErrorState message={error} onRetry={() => void generate()} isRetrying={isGenerating} />
          ) : quiz === null ? (
            <EmptyState hasDocuments={hasDocuments} isGenerating={isGenerating} onGenerate={generate} />
          ) : quiz.status === "pending" || quiz.status === "generating" ? (
            <QuizSkeleton label="Generating quiz" />
          ) : quiz.status === "failed" ? (
            <ErrorState
              message={describeErrorReason(quiz.error_reason)}
              onRetry={() => void generate()}
              isRetrying={isGenerating}
            />
          ) : (
            <QuizTaker
              key={quiz.id}
              questions={quiz.questions}
              isRegenerating={isGenerating}
              onRegenerate={generate}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function EmptyState({
  hasDocuments,
  isGenerating,
  onGenerate,
}: {
  hasDocuments: boolean;
  isGenerating: boolean;
  onGenerate: () => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <p className="text-sm font-medium text-ink">
        {hasDocuments ? "Test what you know" : "No documents yet"}
      </p>
      <p className="max-w-sm text-sm text-ink-muted">
        {hasDocuments
          ? "Generate a multiple-choice quiz grounded in this notebook's material."
          : "Upload a document in the Documents tab first — a quiz needs something to be about."}
      </p>
      {hasDocuments && (
        <button
          type="button"
          onClick={() => void onGenerate()}
          disabled={isGenerating}
          className="mt-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {isGenerating ? "Generating…" : "Generate quiz"}
        </button>
      )}
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

interface QuizQuestion {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

function QuizTaker({
  questions,
  isRegenerating,
  onRegenerate,
}: {
  questions: QuizQuestion[];
  isRegenerating: boolean;
  onRegenerate: () => void;
}) {
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [submitted, setSubmitted] = useState(false);

  const answeredCount = Object.keys(answers).length;
  const allAnswered = answeredCount === questions.length;
  const score = questions.reduce(
    (total, q, i) => total + (answers[i] === q.correct_index ? 1 : 0),
    0,
  );

  const selectAnswer = (questionIndex: number, optionIndex: number) => {
    if (submitted) return;
    setAnswers((prev) => ({ ...prev, [questionIndex]: optionIndex }));
  };

  const retake = () => {
    setAnswers({});
    setSubmitted(false);
  };

  return (
    <div className="pb-10">
      {submitted && (
        <div className="mb-6 rounded-xl border border-line bg-surface p-4 text-center">
          <p className="text-lg font-semibold text-ink">
            {score} / {questions.length} correct
          </p>
        </div>
      )}

      <ol className="space-y-6">
        {questions.map((q, questionIndex) => (
          <li key={questionIndex} className="rounded-xl border border-line bg-surface p-4">
            <p className="text-sm font-medium text-ink">{`${questionIndex + 1}. ${q.question}`}</p>
            <div role="radiogroup" aria-label={`Question ${questionIndex + 1} options`} className="mt-3 space-y-2">
              {q.options.map((option, optionIndex) => (
                <QuizOption
                  key={optionIndex}
                  option={option}
                  isSelected={answers[questionIndex] === optionIndex}
                  isCorrect={optionIndex === q.correct_index}
                  submitted={submitted}
                  onSelect={() => selectAnswer(questionIndex, optionIndex)}
                />
              ))}
            </div>
            {submitted && (
              <p className="mt-3 text-xs leading-relaxed text-ink-muted">{q.explanation}</p>
            )}
          </li>
        ))}
      </ol>

      <div className="mt-6 flex items-center justify-between gap-3">
        {submitted ? (
          <button
            type="button"
            onClick={retake}
            className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-paper"
          >
            Retake
          </button>
        ) : (
          <div className="text-xs text-ink-muted">
            {answeredCount} of {questions.length} answered
          </div>
        )}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRegenerate}
            disabled={isRegenerating}
            className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink-muted transition-colors hover:bg-paper hover:text-ink disabled:opacity-50"
          >
            {isRegenerating ? "Generating…" : "New questions"}
          </button>
          {!submitted && (
            <button
              type="button"
              onClick={() => setSubmitted(true)}
              disabled={!allAnswered}
              className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              Submit
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function QuizOption({
  option,
  isSelected,
  isCorrect,
  submitted,
  onSelect,
}: {
  option: string;
  isSelected: boolean;
  isCorrect: boolean;
  submitted: boolean;
  onSelect: () => void;
}) {
  let className =
    "flex w-full items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors ";
  if (submitted) {
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
      disabled={submitted}
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
