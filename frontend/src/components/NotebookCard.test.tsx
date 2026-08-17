import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { NotebookRecord } from "../lib/api";
import { NotebookCard } from "./NotebookCard";

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

describe("NotebookCard", () => {
  it("shows the notebook name and opens it when clicked", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(
      <NotebookCard notebook={makeNotebook()} onOpen={onOpen} onRename={vi.fn()} onDeleteClick={vi.fn()} />,
    );

    await user.click(screen.getByText("Learning Python"));

    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("shows a goal badge when the notebook has a goal", () => {
    render(
      <NotebookCard
        notebook={makeNotebook({ goal_type: "exam" })}
        onOpen={vi.fn()}
        onRename={vi.fn()}
        onDeleteClick={vi.fn()}
      />,
    );

    expect(screen.getByText("Exam prep")).toBeInTheDocument();
  });

  it("does not show a goal badge when no goal is set", () => {
    render(
      <NotebookCard notebook={makeNotebook()} onOpen={vi.fn()} onRename={vi.fn()} onDeleteClick={vi.fn()} />,
    );

    expect(screen.queryByText(/prep|exploring|skill|custom/i)).not.toBeInTheDocument();
  });

  it("renames the notebook via the pencil icon without opening it", async () => {
    const onOpen = vi.fn();
    const onRename = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(
      <NotebookCard notebook={makeNotebook()} onOpen={onOpen} onRename={onRename} onDeleteClick={vi.fn()} />,
    );

    await user.click(screen.getByLabelText(/rename learning python/i));
    const input = screen.getByLabelText(/notebook name/i);
    await user.clear(input);
    await user.type(input, "New Name{Enter}");

    expect(onRename).toHaveBeenCalledWith("New Name");
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("triggers delete via the trash icon without opening the notebook", async () => {
    const onOpen = vi.fn();
    const onDeleteClick = vi.fn();
    const user = userEvent.setup();
    render(
      <NotebookCard
        notebook={makeNotebook()}
        onOpen={onOpen}
        onRename={vi.fn()}
        onDeleteClick={onDeleteClick}
      />,
    );

    await user.click(screen.getByLabelText(/delete learning python/i));

    expect(onDeleteClick).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
  });
});
