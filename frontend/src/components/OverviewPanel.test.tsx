import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { OverviewPanel } from "./OverviewPanel";

function makeOverview(overrides: Partial<api.OverviewRecord> = {}): api.OverviewRecord {
  return {
    id: "ov-1",
    notebook_id: "notebook-1",
    status: "ready",
    topics: [],
    estimated_minutes: null,
    error_reason: null,
    error_detail: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("OverviewPanel", () => {
  it("shows topics, key concepts, and estimated time when ready", async () => {
    vi.spyOn(api, "getNotebookOverview").mockResolvedValue(
      makeOverview({
        estimated_minutes: 15,
        topics: [
          { title: "Cell Biology", summary: "Covers cell structure.", key_concepts: ["nucleus", "membrane"] },
        ],
      }),
    );

    render(<OverviewPanel notebookId="notebook-1" />);

    expect(await screen.findByText("Cell Biology")).toBeInTheDocument();
    expect(screen.getByText("Covers cell structure.")).toBeInTheDocument();
    expect(screen.getByText("nucleus")).toBeInTheDocument();
    expect(screen.getByText(/15 min to study/i)).toBeInTheDocument();
  });

  it("shows a human-readable message and retry button when generation failed", async () => {
    vi.spyOn(api, "getNotebookOverview").mockResolvedValue(
      makeOverview({ status: "failed", error_reason: "ollama_unreachable" }),
    );

    render(<OverviewPanel notebookId="notebook-1" />);

    expect(await screen.findByRole("button", { name: /try again/i })).toBeInTheDocument();
    expect(screen.queryByText("ollama_unreachable")).not.toBeInTheDocument();
  });

  it("retries generation when 'Try again' is clicked", async () => {
    vi.spyOn(api, "getNotebookOverview").mockResolvedValue(
      makeOverview({ status: "failed", error_reason: "ollama_unreachable" }),
    );
    const regenerateSpy = vi
      .spyOn(api, "regenerateNotebookOverview")
      .mockResolvedValue(makeOverview({ status: "generating" }));
    const user = userEvent.setup();

    render(<OverviewPanel notebookId="notebook-1" />);
    await user.click(await screen.findByRole("button", { name: /try again/i }));

    await waitFor(() => expect(regenerateSpy).toHaveBeenCalledWith("notebook-1"));
    expect(await screen.findByLabelText(/generating overview/i)).toBeInTheDocument();
  });

  it("shows a generating state while the overview is not yet ready", async () => {
    vi.spyOn(api, "getNotebookOverview").mockResolvedValue(makeOverview({ status: "generating" }));

    render(<OverviewPanel notebookId="notebook-1" />);

    expect(await screen.findByLabelText(/generating overview/i)).toBeInTheDocument();
  });
});
