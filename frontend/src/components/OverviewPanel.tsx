import { useOverview } from "../hooks/useOverview";
import { describeErrorReason } from "../lib/errorMessages";

interface OverviewPanelProps {
  notebookId: string;
}

export function OverviewPanel({ notebookId }: OverviewPanelProps) {
  const { overview, isLoading, error, isRegenerating, regenerate } = useOverview(notebookId);

  return (
    <section>
      <h2 className="text-sm font-semibold tracking-tight text-ink">Overview</h2>
      <p className="mt-1 mb-4 text-xs text-ink-muted">
        A summary of everything in this notebook, generated automatically from your documents.
      </p>
      <OverviewBody
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

  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      {overview.estimated_minutes !== null && (
        <p className="mb-3 text-xs text-ink-muted">About {overview.estimated_minutes} min to study</p>
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
