import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { NotebookRecord } from "../lib/api";
import { MobileNav, Sidebar } from "./Sidebar";

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

  it("shows the workspace nav once a notebook is open, with every section selectable", async () => {
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

    // Interview was a disabled "Soon" placeholder until 6.7 landed. Every
    // workspace section is now reachable, so nothing in this nav is inert.
    await user.click(screen.getByRole("button", { name: /^interview$/i }));
    expect(onSelectSection).toHaveBeenCalledWith("interview");
  });

  it("marks the open section as the current page", () => {
    render(
      <Sidebar
        activeNotebook={makeNotebook()}
        activeSection="interview"
        onSelectSection={vi.fn()}
        onGoHome={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /^interview$/i })).toHaveAttribute(
      "aria-current",
      "page",
    );
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

describe("MobileNav", () => {
  const baseProps = {
    activeNotebook: makeNotebook(),
    activeSection: "documents" as const,
    onSelectSection: vi.fn(),
    onGoHome: vi.fn(),
    onClose: vi.fn(),
  };

  it("renders nothing when closed", () => {
    render(<MobileNav {...baseProps} open={false} />);
    expect(screen.queryByRole("dialog", { name: /navigation/i })).not.toBeInTheDocument();
  });

  it("gives phones a way to reach the workspace sections", async () => {
    // Before this drawer existed the only nav lived in a sidebar hidden below
    // `lg`, so a phone could not switch sections at all.
    const onSelectSection = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <MobileNav {...baseProps} open onSelectSection={onSelectSection} onClose={onClose} />,
    );

    await user.click(screen.getByRole("button", { name: /^interview$/i }));

    expect(onSelectSection).toHaveBeenCalledWith("interview");
    // Choosing a destination must also reveal it, not leave the drawer
    // covering the thing just chosen.
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on the backdrop and on Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<MobileNav {...baseProps} open onClose={onClose} />);

    await user.click(screen.getByRole("button", { name: /close navigation/i }));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("closes when going home, so the home screen is not left behind the drawer", async () => {
    const onGoHome = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<MobileNav {...baseProps} open onGoHome={onGoHome} onClose={onClose} />);

    await user.click(screen.getByText(/all notebooks/i));

    expect(onGoHome).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("locks the page behind it from scrolling while open", () => {
    const { unmount } = render(<MobileNav {...baseProps} open />);
    expect(document.body.style.overflow).toBe("hidden");
    unmount();
    expect(document.body.style.overflow).not.toBe("hidden");
  });
});
