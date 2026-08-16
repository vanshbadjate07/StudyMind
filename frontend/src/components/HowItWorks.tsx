const STEPS = [
  {
    title: "Upload",
    description: "Add a PDF of your notes, textbook chapter, or slides.",
  },
  {
    title: "Understand",
    description: "We extract, chunk, and index the content for accurate retrieval.",
  },
  {
    title: "Practice",
    description: "Chat with it, take a generated quiz, or turn it into slides.",
  },
  {
    title: "Prepare",
    description: "Run an adaptive mock interview based on the material.",
  },
];

export function HowItWorks() {
  return (
    <ol className="grid grid-cols-1 divide-y divide-line rounded-lg border border-line sm:grid-cols-2 sm:divide-x sm:divide-y-0 lg:grid-cols-4">
      {STEPS.map((step, index) => (
        <li key={step.title} className="p-4">
          <span className="text-xs font-semibold tracking-wide text-ink-faint">{`0${index + 1}`}</span>
          <h3 className="mt-1 text-sm font-semibold text-ink">{step.title}</h3>
          <p className="mt-1 text-xs leading-relaxed text-ink-muted">{step.description}</p>
        </li>
      ))}
    </ol>
  );
}
