import { describe, expect, it } from "vitest";
import { notebookAccent } from "./notebookAccent";

describe("notebookAccent", () => {
  it("is deterministic — the same notebook id always gets the same accent", () => {
    const id = "9075db99-6316-408b-8110-7b1f4a402c08";
    expect(notebookAccent(id)).toEqual(notebookAccent(id));
  });

  it("returns both a background and text class for any id", () => {
    const accent = notebookAccent("some-notebook-id");
    expect(accent.bg).toMatch(/^bg-/);
    expect(accent.text).toMatch(/^text-/);
  });

  it("does not always return the same accent for different ids", () => {
    // Not a strict distribution test (that's better covered by a targeted
    // script, not the suite) — just a sanity check that this isn't
    // hardcoded to a single bucket regardless of input.
    const ids = ["a", "b", "c", "d", "e", "f", "g", "h"];
    const accents = new Set(ids.map((id) => notebookAccent(id).bg));
    expect(accents.size).toBeGreaterThan(1);
  });
});
