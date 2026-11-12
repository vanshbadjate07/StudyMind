import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { SlidesView } from "./SlidesView";

function makePresentation(
  overrides: Partial<api.PresentationRecord> = {},
): api.PresentationRecord {
  return {
    id: "pres-1",
    notebook_id: "nb-1",
    status: "ready",
    slide_count: 10,
    style: "concise",
    focus: null,
    error_reason: null,
    error_detail: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("SlidesView", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows an upload prompt when the notebook has no documents yet", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(null);

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments={false} />);

    expect(await screen.findByText(/no documents yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate slides/i })).not.toBeInTheDocument();
  });

  it("shows the setup form, defaulted to a 10-slide concise deck", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(null);

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText(/set up your deck/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/number of slides/i)).toHaveValue(10);
    expect(screen.getByRole("button", { name: /^concise/i })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText(/generates a 10-slide deck in concise style/i)).toBeInTheDocument();
  });

  it("stepper and presets both move the slide count, within the 5-30 bounds", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(null);
    const user = userEvent.setup();

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/set up your deck/i);

    const count = screen.getByLabelText(/number of slides/i);
    await user.click(screen.getByRole("button", { name: /increase slide count/i }));
    expect(count).toHaveValue(11);

    await user.click(screen.getByRole("button", { name: "20" }));
    expect(count).toHaveValue(20);
    expect(screen.getByText(/generates a 20-slide deck/i)).toBeInTheDocument();

    // Upper bound: the increase button is disabled at the max.
    await user.clear(count);
    await user.type(count, "30");
    await user.tab();
    expect(screen.getByRole("button", { name: /increase slide count/i })).toBeDisabled();
  });

  it("clamps an out-of-range typed count on blur rather than sending it", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(null);
    const generateSpy = vi
      .spyOn(api, "generateNotebookPresentation")
      .mockResolvedValue(makePresentation({ status: "pending", slide_count: null }));
    const user = userEvent.setup();

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/set up your deck/i);

    const count = screen.getByLabelText(/number of slides/i);
    await user.clear(count);
    await user.type(count, "99");
    await user.tab();
    expect(count).toHaveValue(30);

    await user.click(screen.getByRole("button", { name: /generate slides/i }));
    expect(generateSpy).toHaveBeenCalledWith(
      "nb-1",
      expect.objectContaining({ slide_count: 30 }),
    );
  });

  it("sends the chosen style and trimmed focus, omitting focus when blank", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(null);
    const generateSpy = vi
      .spyOn(api, "generateNotebookPresentation")
      .mockResolvedValue(makePresentation({ status: "pending", slide_count: null }));
    const user = userEvent.setup();

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/set up your deck/i);

    await user.click(screen.getByRole("button", { name: /^exam focused/i }));
    await user.type(screen.getByLabelText(/focus on/i), "   chapter 3   ");
    await user.click(screen.getByRole("button", { name: /generate slides/i }));

    expect(generateSpy).toHaveBeenCalledWith("nb-1", {
      slide_count: 10,
      style: "exam_focused",
      focus: "chapter 3",
    });
  });

  it("omits focus entirely when the field is only whitespace", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(null);
    const generateSpy = vi
      .spyOn(api, "generateNotebookPresentation")
      .mockResolvedValue(makePresentation({ status: "pending", slide_count: null }));
    const user = userEvent.setup();

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/set up your deck/i);

    await user.type(screen.getByLabelText(/focus on/i), "    ");
    await user.click(screen.getByRole("button", { name: /generate slides/i }));

    expect(generateSpy).toHaveBeenCalledWith("nb-1", {
      slide_count: 10,
      style: "concise",
      focus: undefined,
    });
  });

  it("shows a generating state while the deck is being written", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(
      makePresentation({ status: "generating", slide_count: null }),
    );

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText(/generating slides/i)).toBeInTheDocument();
    expect(screen.queryByText(/set up your deck/i)).not.toBeInTheDocument();
  });

  it("shows the ready deck with a download link and its settings", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(
      makePresentation({ slide_count: 12, style: "visual_heavy", focus: "case studies" }),
    );

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByText(/your deck is ready/i)).toBeInTheDocument();
    expect(screen.getByText(/12 slides/)).toBeInTheDocument();
    expect(screen.getByText(/Visual/)).toBeInTheDocument();
    expect(screen.getByText(/case studies/)).toBeInTheDocument();

    const link = screen.getByRole("link", { name: /download deck/i });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("/notebooks/nb-1/presentation/download"),
    );
    expect(link).toHaveAttribute("download");
  });

  it("'New deck' reopens setup without discarding the existing deck", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(makePresentation());
    const user = userEvent.setup();

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/your deck is ready/i);

    await user.click(screen.getByRole("button", { name: /new deck/i }));
    expect(screen.getByText(/set up your deck/i)).toBeInTheDocument();
    expect(screen.queryByText(/your deck is ready/i)).not.toBeInTheDocument();
  });

  it("explains a failed generation in plain language, with a way back to setup", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(
      makePresentation({ status: "failed", error_reason: "llm_unreachable", slide_count: null }),
    );
    const user = userEvent.setup();

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/couldn't reach the ai service/i);
    await user.click(screen.getByRole("button", { name: /try again/i }));
    expect(screen.getByText(/set up your deck/i)).toBeInTheDocument();
  });

  it("surfaces a 409 from the backend when generation is already running", async () => {
    vi.spyOn(api, "getNotebookPresentation").mockResolvedValue(null);
    vi.spyOn(api, "generateNotebookPresentation").mockRejectedValue(
      new api.ApiError(409, "Presentation generation is already in progress for this notebook."),
    );
    const user = userEvent.setup();

    render(<SlidesView notebookId="nb-1" notebookName="ML Notes" hasDocuments />);
    await screen.findByText(/set up your deck/i);

    await user.click(screen.getByRole("button", { name: /generate slides/i }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(/already in progress/i);
    });
  });
});
