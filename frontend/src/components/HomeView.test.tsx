import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { NotebookRecord } from "../lib/api";
import { HomeView } from "./HomeView";

function makeNotebook(overrides: Partial<NotebookRecord> = {}): NotebookRecord {
  return {
    id: "nb-1",
    name: "Learning Python",
    goal_type: null,
    goal_description: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("HomeView", () => {
  it("always shows a create-notebook action, even with no notebooks yet", () => {
    render(
      <HomeView
        notebooks={[]}
        isLoading={false}
        error={null}
        onCreateNotebook={vi.fn()}
        onOpenNotebook={vi.fn()}
        onRenameNotebook={vi.fn()}
        onDeleteNotebook={vi.fn()}
      />,
    );

    expect(screen.getByText(/new notebook/i)).toBeInTheDocument();
  });

  it("lists every notebook as a card", () => {
    render(
      <HomeView
        notebooks={[makeNotebook({ id: "a", name: "Python" }), makeNotebook({ id: "b", name: "Biology" })]}
        isLoading={false}
        error={null}
        onCreateNotebook={vi.fn()}
        onOpenNotebook={vi.fn()}
        onRenameNotebook={vi.fn()}
        onDeleteNotebook={vi.fn()}
      />,
    );

    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("Biology")).toBeInTheDocument();
  });

  it("opens a notebook when its card is clicked", async () => {
    const onOpenNotebook = vi.fn();
    const user = userEvent.setup();
    render(
      <HomeView
        notebooks={[makeNotebook()]}
        isLoading={false}
        error={null}
        onCreateNotebook={vi.fn()}
        onOpenNotebook={onOpenNotebook}
        onRenameNotebook={vi.fn()}
        onDeleteNotebook={vi.fn()}
      />,
    );

    await user.click(screen.getByText("Learning Python"));

    expect(onOpenNotebook).toHaveBeenCalledWith("nb-1");
  });

  it("calls onCreateNotebook when the create tile is clicked", async () => {
    const onCreateNotebook = vi.fn();
    const user = userEvent.setup();
    render(
      <HomeView
        notebooks={[]}
        isLoading={false}
        error={null}
        onCreateNotebook={onCreateNotebook}
        onOpenNotebook={vi.fn()}
        onRenameNotebook={vi.fn()}
        onDeleteNotebook={vi.fn()}
      />,
    );

    await user.click(screen.getByText(/new notebook/i));

    expect(onCreateNotebook).toHaveBeenCalledTimes(1);
  });

  it("asks for confirmation before deleting a notebook", async () => {
    const onDeleteNotebook = vi.fn();
    const user = userEvent.setup();
    render(
      <HomeView
        notebooks={[makeNotebook()]}
        isLoading={false}
        error={null}
        onCreateNotebook={vi.fn()}
        onOpenNotebook={vi.fn()}
        onRenameNotebook={vi.fn()}
        onDeleteNotebook={onDeleteNotebook}
      />,
    );

    await user.click(screen.getByLabelText(/delete learning python/i));
    expect(screen.getByText(/delete this notebook/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^delete$/i }));

    await waitFor(() => expect(onDeleteNotebook).toHaveBeenCalledWith("nb-1"));
  });

  it("shows a server error when notebooks fail to load", () => {
    render(
      <HomeView
        notebooks={[]}
        isLoading={false}
        error="Couldn't reach the server."
        onCreateNotebook={vi.fn()}
        onOpenNotebook={vi.fn()}
        onRenameNotebook={vi.fn()}
        onDeleteNotebook={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/couldn't reach the server/i);
  });
});
