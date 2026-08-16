import type { DocumentStatus } from "../lib/api";

const STATUS_LABEL: Record<DocumentStatus, string> = {
  pending: "Queued",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
};

const STATUS_STYLES: Record<DocumentStatus, string> = {
  pending: "bg-status-pending-subtle text-status-pending",
  processing: "bg-status-processing-subtle text-status-processing",
  ready: "bg-status-ready-subtle text-status-ready",
  failed: "bg-status-failed-subtle text-status-failed",
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const isInFlight = status === "pending" || status === "processing";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${STATUS_STYLES[status]}`}
    >
      {isInFlight && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden="true" />
      )}
      {STATUS_LABEL[status]}
    </span>
  );
}
