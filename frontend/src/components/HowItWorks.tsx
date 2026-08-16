import type { ReactNode } from "react";

const STEPS: { title: string; description: string; icon: ReactNode }[] = [
  {
    title: "Upload",
    description: "Add a PDF of your notes, textbook chapter, or slides.",
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 15V4m0 0 3.5 3.5M12 4 8.5 7.5M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"
      />
    ),
  },
  {
    title: "Understand",
    description: "We extract, chunk, and index the content for accurate retrieval.",
    icon: (
      <>
        <circle cx="10.5" cy="10.5" r="6.5" strokeLinecap="round" strokeLinejoin="round" />
        <path strokeLinecap="round" strokeLinejoin="round" d="m20 20-4.8-4.8" />
      </>
    ),
  },
  {
    title: "Practice",
    description: "Chat with it, take a generated quiz, or turn it into slides.",
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M4 5h16v10H8l-4 4V5Z"
      />
    ),
  },
  {
    title: "Prepare",
    description: "Run an adaptive mock interview based on the material.",
    icon: (
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 3a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3ZM6 11a6 6 0 0 0 12 0M12 17v4m-3 0h6"
      />
    ),
  },
];

export function HowItWorks() {
  return (
    <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {STEPS.map((step, index) => (
        <li
          key={step.title}
          className="rounded-xl border border-line bg-surface p-4 shadow-sm transition-shadow hover:shadow-md"
        >
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-subtle text-brand-ink">
              <svg
                aria-hidden="true"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.6}
                className="h-4 w-4"
              >
                {step.icon}
              </svg>
            </span>
            <span className="text-[11px] font-semibold tracking-wide text-ink-faint">
              STEP {index + 1}
            </span>
          </div>
          <h3 className="mt-3 text-sm font-semibold text-ink">{step.title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-ink-muted">{step.description}</p>
        </li>
      ))}
    </ol>
  );
}
