import { Fragment, type ReactNode } from "react";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Bolds any occurrence of the given key terms within `text` (case-
 * insensitive, longest term first so e.g. "neural networks" isn't partially
 * matched by a shorter unrelated term first). Terms are StudyMind's own
 * generated `key_concepts` — deterministic, structured data — rather than
 * asking the LLM to emit markdown itself, which proved unreliable for
 * following formatting instructions elsewhere in this app. */
export function highlightKeyTerms(text: string, terms: string[]): ReactNode {
  const uniqueTerms = Array.from(new Set(terms.map((t) => t.trim()).filter(Boolean)));
  if (uniqueTerms.length === 0) return text;

  const sorted = [...uniqueTerms].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(${sorted.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);
  const lowerTerms = new Set(sorted.map((term) => term.toLowerCase()));

  return parts.map((part, index) =>
    lowerTerms.has(part.toLowerCase()) ? (
      <strong key={index} className="font-semibold text-ink">
        {part}
      </strong>
    ) : (
      <Fragment key={index}>{part}</Fragment>
    ),
  );
}
