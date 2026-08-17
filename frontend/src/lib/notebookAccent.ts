const ACCENTS = [
  { bg: "bg-[var(--color-accent-gold-subtle)]", text: "text-[var(--color-accent-gold)]" },
  { bg: "bg-[var(--color-accent-forest-subtle)]", text: "text-[var(--color-accent-forest)]" },
  { bg: "bg-[var(--color-accent-steel-subtle)]", text: "text-[var(--color-accent-steel)]" },
  { bg: "bg-[var(--color-accent-berry-subtle)]", text: "text-[var(--color-accent-berry)]" },
  { bg: "bg-[var(--color-accent-rust-subtle)]", text: "text-[var(--color-accent-rust)]" },
];

/** Deterministically assigns one of a small curated set of muted accent
 * colors to a notebook, based on its id — gives each notebook card a
 * distinct, stable identity without needing user-configured colors or a
 * full rainbow palette. */
export function notebookAccent(notebookId: string): { bg: string; text: string } {
  let hash = 0;
  for (let i = 0; i < notebookId.length; i++) {
    hash = (hash * 31 + notebookId.charCodeAt(i)) | 0;
  }
  const index = Math.abs(hash) % ACCENTS.length;
  return ACCENTS[index];
}
