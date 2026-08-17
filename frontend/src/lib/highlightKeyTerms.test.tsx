import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { highlightKeyTerms } from "./highlightKeyTerms";

describe("highlightKeyTerms", () => {
  it("bolds occurrences of the given terms", () => {
    render(<p>{highlightKeyTerms("Covers neural networks and backpropagation.", ["neural networks"])}</p>);

    const strong = screen.getByText("neural networks");
    expect(strong.tagName).toBe("STRONG");
  });

  it("matches case-insensitively but preserves the original casing in the text", () => {
    render(<p>{highlightKeyTerms("Neural Networks are covered here.", ["neural networks"])}</p>);

    expect(screen.getByText("Neural Networks").tagName).toBe("STRONG");
  });

  it("prefers the longest term when one term is a substring of another", () => {
    render(
      <p>{highlightKeyTerms("Covers neural networks in depth.", ["neural", "neural networks"])}</p>,
    );

    expect(screen.getByText("neural networks").tagName).toBe("STRONG");
    expect(screen.queryByText("neural")).not.toBeInTheDocument();
  });

  it("returns the plain text unchanged when no terms match", () => {
    const { container } = render(<p>{highlightKeyTerms("Nothing to highlight here.", ["unrelated"])}</p>);

    expect(container.querySelector("strong")).not.toBeInTheDocument();
    expect(screen.getByText("Nothing to highlight here.")).toBeInTheDocument();
  });

  it("returns the plain text unchanged when there are no terms at all", () => {
    const { container } = render(<p>{highlightKeyTerms("Some text.", [])}</p>);

    expect(container.querySelector("strong")).not.toBeInTheDocument();
  });
});
