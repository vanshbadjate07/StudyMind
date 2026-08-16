import { useOverview } from "../hooks/useOverview";
import { describeErrorReason } from "../lib/errorMessages";

interface OverviewPanelProps {
  documentId: string;
}

export function OverviewPanel({ documentId }: OverviewPanelProps) {
  const { overview, isLoading, error, isRegenerating, regenerate } = useOverview(documentId);

  if (isLoading) {
    return <OverviewSkeleton label="Loading overview" />;
  }

  if (error) {
    return (
      <div className="border-t border-line px-4 py-4">
        <p role="alert" className="text-sm text-status-failed">
          {error}
        </p>
      </div>
    );
  }

  if (overview === null || overview.status === "pending" || overview.status === "generating") {
    return <OverviewSkeleton label="Generating overview" />;
  }

  if (overview.status === "failed") {
    return (
      <div className="border-t border-line px-4 py-4">
        <p className="text-sm text-status-failed">{describeErrorReason(overview.error_reason)}</p>
        <button
          type="button"
          onClick={() => void regenerate()}
          disabled={isRegenerating}
          className="mt-2 rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-ink transition-colors hover:bg-paper disabled:opacity-50"
        >
          {isRegenerating ? "Retrying..." : "Try again"}
        </button>
      </div>
    );
  }

  return (
    <div className="border-t border-line px-4 py-4">
      {overview.estimated_minutes !== null && (
        <p className="mb-3 text-xs text-ink-muted">About {overview.estimated_minutes} min to study</p>
      )}
      <ol className="space-y-3">
        {overview.topics.map((topic) => (
          <li key={topic.title}>
            <p className="text-sm font-semibold text-ink">{topic.title}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{topic.summary}</p>
            {topic.key_concepts.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {topic.key_concepts.map((concept) => (
                  <span
                    key={concept}
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
    <div className="space-y-2 border-t border-line px-4 py-4" aria-busy="true" aria-label={label}>
      <div className="h-3 w-40 animate-pulse rounded bg-line" />
      <div className="h-3 w-full animate-pulse rounded bg-line" />
      <div className="h-3 w-5/6 animate-pulse rounded bg-line" />
    </div>
  );
}
