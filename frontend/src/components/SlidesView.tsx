import { useState } from "react";
import { usePresentation } from "../hooks/usePresentation";
import {
  presentationDownloadUrl,
  type PresentationGenerateOptions,
  type PresentationStyle,
} from "../lib/api";
import { describeErrorReason } from "../lib/errorMessages";

const SLIDE_COUNT_MIN = 5;
const SLIDE_COUNT_MAX = 30;
const SLIDE_COUNT_PRESETS = [8, 10, 15, 20];

const DEFAULT_OPTIONS: PresentationGenerateOptions = {
  slide_count: 10,
  style: "concise",
  focus: "",
};

const STYLE_OPTIONS: { value: PresentationStyle; label: string; description: string }[] = [
  { value: "concise", label: "Concise", description: "Tight bullets, the essentials only." },
  { value: "exam_focused", label: "Exam focused", description: "Definitions, formulas, things worth memorizing." },
  { value: "visual_heavy", label: "Visual", description: "Favours diagrams and comparisons over prose." },
];

const STYLE_LABELS: Record<string, string> = {
  concise: "Concise",
  exam_focused: "Exam focused",
  visual_heavy: "Visual",
};

function clampCount(value: number): number {
  if (Number.isNaN(value)) return SLIDE_COUNT_MIN;
  return Math.min(SLIDE_COUNT_MAX, Math.max(SLIDE_COUNT_MIN, Math.round(value)));
}

interface SlidesViewProps {
  notebookId: string;
  notebookName: string;
  hasDocuments: boolean;
}

export function SlidesView({ notebookId, notebookName, hasDocuments }: SlidesViewProps) {
  const { presentation, isLoading, error, isGenerating, generate } = usePresentation(notebookId);
  // Not persisted server-side beyond what the generated deck records, kept
  // here so reopening setup ("New deck") starts from the last choices rather
  // than resetting to defaults — same reasoning as QuizView's lastOptions.
  const [lastOptions, setLastOptions] = useState<PresentationGenerateOptions>(DEFAULT_OPTIONS);
  // Setup shows before the first deck exists, and again only when the user
  // explicitly asks to reconfigure — never re-shown by a poll tick, which
  // would otherwise replace a finished deck mid-view.
  const [isConfiguring, setIsConfiguring] = useState(false);

  const handleGenerate = (options: PresentationGenerateOptions) => {
    setLastOptions(options);
    setIsConfiguring(false);
    void generate(options);
  };

  // isGenerating is excluded so the form can't flash back in the gap between
  // submitting and `presentation` updating from the response.
  const showSetup =
    !isLoading && !error && !isGenerating && (presentation === null || isConfiguring);
  const isBusy =
    isGenerating || presentation?.status === "pending" || presentation?.status === "generating";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-line px-6 py-4 lg:px-12">
        <h1 className="text-lg font-semibold tracking-tight text-ink">Slides</h1>
        <p className="mt-0.5 text-xs text-ink-muted">
          Turn the documents in "{notebookName}" into a slide deck you can download.
        </p>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-6 lg:px-12">
        <div className="mx-auto w-full max-w-3xl">
          {isLoading ? (
            <SlidesSkeleton label="Loading slides" />
          ) : error ? (
            <ErrorState
              message={error}
              onRetry={() => void generate(lastOptions)}
              isRetrying={isGenerating}
            />
          ) : !hasDocuments ? (
            <NoDocumentsState />
          ) : showSetup ? (
            <SlidesSetupForm
              initial={lastOptions}
              isGenerating={isGenerating}
              onGenerate={handleGenerate}
            />
          ) : isBusy ? (
            <SlidesSkeleton label="Generating slides" />
          ) : presentation?.status === "failed" ? (
            <ErrorState
              message={describeErrorReason(presentation.error_reason)}
              onRetry={() => setIsConfiguring(true)}
              isRetrying={isGenerating}
            />
          ) : presentation ? (
            <DeckReady
              notebookId={notebookId}
              slideCount={presentation.slide_count}
              style={presentation.style}
              focus={presentation.focus}
              updatedAt={presentation.updated_at}
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
        Upload a document in the Documents tab first — a deck needs something to be about.
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

function SlidesSetupForm({
  initial,
  isGenerating,
  onGenerate,
}: {
  initial: PresentationGenerateOptions;
  isGenerating: boolean;
  onGenerate: (options: PresentationGenerateOptions) => void;
}) {
  const [slideCount, setSlideCount] = useState(initial.slide_count);
  const [style, setStyle] = useState<PresentationStyle>(initial.style);
  const [focus, setFocus] = useState(initial.focus ?? "");

  const styleLabel = STYLE_OPTIONS.find((option) => option.value === style)?.label ?? "Concise";
  const summary = [
    `Generates a ${slideCount}-slide deck in ${styleLabel.toLowerCase()} style`,
    "from this notebook's material",
    focus.trim() ? `, focused on "${focus.trim()}"` : "",
    ".",
  ].join(" ");

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    onGenerate({
      slide_count: clampCount(slideCount),
      style,
      focus: focus.trim() || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-line bg-surface p-5">
      <h2 className="text-sm font-semibold text-ink">Set up your deck</h2>
      <p className="mt-1 text-xs text-ink-muted">
        Customize what gets generated from this notebook's material.
      </p>

      <div className="mt-5">
        <label htmlFor="slide-count" className="text-xs font-medium text-ink-muted">
          Number of slides
        </label>
        <div className="mt-2 flex items-center gap-3">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setSlideCount((n) => clampCount(n - 1))}
              disabled={slideCount <= SLIDE_COUNT_MIN}
              aria-label="Decrease slide count"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line text-ink transition-colors hover:bg-paper disabled:opacity-40"
            >
              <MinusIcon />
            </button>
            <input
              id="slide-count"
              type="number"
              min={SLIDE_COUNT_MIN}
              max={SLIDE_COUNT_MAX}
              value={slideCount}
              onChange={(event) => setSlideCount(Number(event.target.value))}
              onBlur={() => setSlideCount((n) => clampCount(n))}
              className="h-8 w-14 rounded-lg border border-line text-center text-sm text-ink focus:border-brand focus:outline-none"
            />
            <button
              type="button"
              onClick={() => setSlideCount((n) => clampCount(n + 1))}
              disabled={slideCount >= SLIDE_COUNT_MAX}
              aria-label="Increase slide count"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line text-ink transition-colors hover:bg-paper disabled:opacity-40"
            >
              <PlusIcon />
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {SLIDE_COUNT_PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => setSlideCount(preset)}
                aria-pressed={slideCount === preset}
                className={`rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                  slideCount === preset
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
        <p className="text-xs font-medium text-ink-muted">Style</p>
        <div className="mt-2 grid gap-2 sm:grid-cols-3">
          {STYLE_OPTIONS.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setStyle(option.value)}
              aria-pressed={style === option.value}
              className={`rounded-lg border p-2.5 text-left transition-colors ${
                style === option.value ? "border-brand bg-brand-subtle" : "border-line hover:bg-paper"
              }`}
            >
              <span className="text-sm font-medium text-ink">{option.label}</span>
              <p className="mt-0.5 text-xs text-ink-muted">{option.description}</p>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-5">
        <label htmlFor="slides-focus" className="text-xs font-medium text-ink-muted">
          Focus on (optional)
        </label>
        <input
          id="slides-focus"
          type="text"
          value={focus}
          onChange={(event) => setFocus(event.target.value)}
          maxLength={200}
          placeholder="e.g. chapter 3, only the case studies"
          className="mt-1 w-full rounded-lg border border-line px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
        />
      </div>

      <p className="mt-4 rounded-lg bg-paper px-3 py-2 text-xs leading-relaxed text-ink-muted">
        {summary}
      </p>

      <button
        type="submit"
        disabled={isGenerating}
        className="mt-4 w-full rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
      >
        {isGenerating ? "Generating…" : "Generate slides"}
      </button>
    </form>
  );
}

function DeckReady({
  notebookId,
  slideCount,
  style,
  focus,
  updatedAt,
  onReconfigure,
}: {
  notebookId: string;
  slideCount: number | null;
  style: string | null;
  focus: string | null;
  updatedAt: string;
  onReconfigure: () => void;
}) {
  const styleLabel = style ? (STYLE_LABELS[style] ?? style) : null;

  return (
    <div className="rounded-xl border border-line bg-surface p-5">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-subtle text-brand-ink">
          <DeckIcon />
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-ink">Your deck is ready</h2>
          <p className="mt-0.5 text-xs text-ink-muted">
            {[
              slideCount === null ? null : `${slideCount} slide${slideCount === 1 ? "" : "s"}`,
              styleLabel,
              focus ? `focused on "${focus}"` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
      </div>

      <dl className="mt-4 grid gap-3 border-t border-line pt-4 sm:grid-cols-2">
        <div>
          <dt className="text-[11px] font-medium tracking-wider text-ink-faint uppercase">Format</dt>
          <dd className="mt-0.5 text-sm text-ink">PowerPoint (.pptx)</dd>
        </div>
        <div>
          <dt className="text-[11px] font-medium tracking-wider text-ink-faint uppercase">Generated</dt>
          <dd className="mt-0.5 text-sm text-ink">
            {new Date(updatedAt).toLocaleString(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </dd>
        </div>
      </dl>

      <div className="mt-5 flex flex-wrap gap-2">
        {/* A plain anchor, not fetch(): the browser handles the download,
            filename and progress itself, and the file never has to pass
            through JS memory. */}
        <a
          href={presentationDownloadUrl(notebookId)}
          download
          className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
        >
          <DownloadIcon />
          Download deck
        </a>
        <button
          type="button"
          onClick={onReconfigure}
          className="rounded-lg border border-line px-4 py-2 text-sm font-medium text-ink transition-colors hover:bg-paper"
        >
          New deck
        </button>
      </div>

      <p className="mt-3 text-xs text-ink-faint">
        Generating a new deck replaces this one.
      </p>
    </div>
  );
}

function SlidesSkeleton({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="rounded-xl border border-line bg-surface p-5">
      <p className="text-sm font-medium text-ink">{label}…</p>
      <p className="mt-1 text-xs text-ink-muted">
        Writing slides from your material. This usually takes under a minute.
      </p>
      <div className="mt-5 grid gap-2.5 sm:grid-cols-2">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="animate-pulse rounded-lg border border-line bg-paper p-3">
            <div className="h-2.5 w-2/3 rounded bg-line" />
            <div className="mt-2 h-2 w-full rounded bg-line" />
            <div className="mt-1.5 h-2 w-5/6 rounded bg-line" />
          </div>
        ))}
      </div>
    </div>
  );
}

function MinusIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5">
      <path strokeLinecap="round" d="M5 12h14" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-3.5 w-3.5">
      <path strokeLinecap="round" d="M12 5v14M5 12h14" />
    </svg>
  );
}

function DeckIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} className="h-5 w-5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 5h16v11H4V5Zm4 15h8M12 16v4" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="h-4 w-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v11m0 0 4-4m-4 4-4-4M5 19h14" />
    </svg>
  );
}
