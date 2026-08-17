import { useState } from "react";
import { useOverview } from "../hooks/useOverview";
import { describeErrorReason } from "../lib/errorMessages";

interface OverviewPanelProps {
  notebookId: string;
  /** Changes whenever the notebook's document set changes (a document
   * became ready, failed, was added, or was removed) — see useOverview's
   * doc comment for why this is needed to catch a regeneration that
   * happens after the overview already looked settled. */
  watchKey: string;
}

export function OverviewPanel({ notebookId, watchKey }: OverviewPanelProps) {
  const { overview, isLoading, error, isRegenerating, regenerate } = useOverview(notebookId, watchKey);

  return (
    <section>
      <h2 className="text-sm font-semibold tracking-tight text-ink">Overview</h2>
      <p className="mt-1 mb-4 text-xs text-ink-muted">
        What this notebook is about, generated automatically from your documents.
      </p>
      <OverviewBody
        // Remounts (resetting the "show topic breakdown" toggle) whenever
        // the active notebook changes — without this, OverviewBody stays
        // mounted in place across a notebook switch (same position in the
        // tree, just new props) and its expanded/collapsed state would
        // otherwise leak from one notebook to the next.
        key={notebookId}
        isLoading={isLoading}
        error={error}
        overview={overview}
        isRegenerating={isRegenerating}
        onRegenerate={regenerate}
      />
    </section>
  );
}

interface OverviewBodyProps {
  isLoading: boolean;
  error: string | null;
  overview: ReturnType<typeof useOverview>["overview"];
  isRegenerating: boolean;
  onRegenerate: () => void;
}

function OverviewBody({ isLoading, error, overview, isRegenerating, onRegenerate }: OverviewBodyProps) {
  const [showDetails, setShowDetails] = useState(false);

  if (isLoading) {
    return <OverviewSkeleton label="Loading overview" />;
  }

  if (error) {
    return (
      <p role="alert" className="text-sm text-status-failed">
        {error}
      </p>
    );
  }

  if (overview === null || overview.status === "pending" || overview.status === "generating") {
    return <OverviewSkeleton label="Generating overview" />;
  }

  if (overview.status === "failed") {
    return (
      <div>
        <p className="text-sm text-status-failed">{describeErrorReason(overview.error_reason)}</p>
        <button
          type="button"
          onClick={onRegenerate}
          disabled={isRegenerating}
          className="mt-2 rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-paper disabled:opacity-50"
        >
          {isRegenerating ? "Retrying..." : "Try again"}
        </button>
      </div>
    );
  }

  const hasDetails = overview.topics.length > 0;

  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      {overview.short_summary ? (
        <p className="text-sm leading-relaxed text-ink">{overview.short_summary}</p>
      ) : (
        <p className="text-sm leading-relaxed text-ink-muted">No summary available yet.</p>
      )}

      {hasDetails && (
        <div className={showDetails ? "mt-4 border-t border-line pt-4" : "mt-3"}>
          <button
            type="button"
            onClick={() => setShowDetails((value) => !value)}
            aria-expanded={showDetails}
            className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted transition-colors hover:text-ink"
          >
            {showDetails ? "Hide topic breakdown" : "Show topic breakdown"}
            <ChevronIcon direction={showDetails ? "up" : "down"} />
          </button>

          {showDetails && (
            <div className="mt-3">
              {overview.estimated_minutes !== null && (
                <p className="mb-3 text-xs text-ink-muted">
                  About {overview.estimated_minutes} min to study
                </p>
              )}
              <ol className="space-y-3">
                {overview.topics.map((topic, topicIndex) => (
                  <li key={`${topicIndex}-${topic.title}`}>
                    <p className="text-sm font-semibold text-ink">{topic.title}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{topic.summary}</p>
                    {topic.key_concepts.length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {topic.key_concepts.map((concept, conceptIndex) => (
                          <span
                            key={`${conceptIndex}-${concept}`}
                            className="rounded-full border border-line px-2 py-0.5 text-[11px] text-ink-muted"
                          >
                            {concept}
                          </span>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ChevronIcon({ direction }: { direction: "up" | "down" }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      className={`h-3 w-3 transition-transform ${direction === "up" ? "rotate-180" : ""}`}
    >
      <path strokeLinecap="round" strokeLinejoin="round" d="m6 9 6 6 6-6" />
    </svg>
  );
}

function OverviewSkeleton({ label }: { label: string }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label={label}>
      <div className="h-3 w-40 animate-pulse rounded bg-line" />
      <div className="h-3 w-full animate-pulse rounded bg-line" />
      <div className="h-3 w-5/6 animate-pulse rounded bg-line" />
    </div>
  );
}
