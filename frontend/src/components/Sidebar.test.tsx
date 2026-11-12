import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { NotebookRecord } from "../lib/api";
import { Sidebar } from "./Sidebar";

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

describe("Sidebar", () => {
  it("hides the workspace nav and notebook identity when no notebook is open", () => {
    render(
      <Sidebar activeNotebook={null} activeSection="documents" onSelectSection={vi.fn()} onGoHome={vi.fn()} />,
    );

    expect(screen.queryByRole("navigation", { name: /workspace sections/i })).not.toBeInTheDocument();
  });

  it("shows the open notebook's name and its goal", () => {
    render(
      <Sidebar
        activeNotebook={makeNotebook({ goal_type: "exam" })}
        activeSection="documents"
        onSelectSection={vi.fn()}
        onGoHome={vi.fn()}
      />,
    );

    expect(screen.getByText("Learning Python")).toBeInTheDocument();
    expect(screen.getByText("Exam prep")).toBeInTheDocument();
  });

  it("shows the workspace nav once a notebook is open, with Chat, Quiz, and Documents selectable", async () => {
    const onSelectSection = vi.fn();
    const user = userEvent.setup();
    render(
      <Sidebar
        activeNotebook={makeNotebook()}
        activeSection="documents"
        onSelectSection={onSelectSection}
        onGoHome={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /chat/i }));
    expect(onSelectSection).toHaveBeenCalledWith("chat");

    await user.click(screen.getByRole("button", { name: /^quiz$/i }));
    expect(onSelectSection).toHaveBeenCalledWith("quiz");

    await user.click(screen.getByRole("button", { name: /^slides$/i }));
    expect(onSelectSection).toHaveBeenCalledWith("slides");
  });

  it("does not let the user click into a 'Soon' section", async () => {
    const onSelectSection = vi.fn();
    const user = userEvent.setup();
    render(
      <Sidebar
        activeNotebook={makeNotebook()}
        activeSection="documents"
        onSelectSection={onSelectSection}
        onGoHome={vi.fn()}
      />,
    );

    // "Soon" items render as a non-interactive div, not a button. Slides used
    // to be one of these; Interview is the remaining unbuilt section.
    expect(screen.queryByRole("button", { name: /interview/i })).not.toBeInTheDocument();
    await user.click(screen.getByText("Interview"));
    expect(onSelectSection).not.toHaveBeenCalled();
  });

  it("goes home when the logo or 'All notebooks' link is clicked", async () => {
    const onGoHome = vi.fn();
    const user = userEvent.setup();
    render(
      <Sidebar
        activeNotebook={makeNotebook()}
        activeSection="documents"
        onSelectSection={vi.fn()}
        onGoHome={onGoHome}
      />,
    );

    await user.click(screen.getByText(/all notebooks/i));

    expect(onGoHome).toHaveBeenCalledTimes(1);
  });

  it("goes home when the logo is clicked", async () => {
    const onGoHome = vi.fn();
    const user = userEvent.setup();
    render(
      <Sidebar
        activeNotebook={makeNotebook()}
        activeSection="documents"
        onSelectSection={vi.fn()}
        onGoHome={onGoHome}
      />,
    );

    await user.click(screen.getByRole("button", { name: /studymind/i }));

    expect(onGoHome).toHaveBeenCalledTimes(1);
  });
});
