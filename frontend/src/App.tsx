import { DocumentList } from "./components/DocumentList";
import { HowItWorks } from "./components/HowItWorks";
import { Sidebar } from "./components/Sidebar";
import { UploadDropzone } from "./components/UploadDropzone";
import { useDocuments } from "./hooks/useDocuments";

function App() {
  const { documents, isLoading, error, addDocument, removeDocument } = useDocuments();

  return (
    <div className="flex h-screen overflow-hidden bg-paper">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <header className="flex items-center gap-2.5 border-b border-line bg-surface px-6 py-4 lg:hidden">
          <Logo />
          <div>
            <p className="text-sm font-semibold tracking-tight text-ink">StudyMind</p>
            <p className="text-xs text-ink-muted">Your material, understood.</p>
          </div>
        </header>

        <main className="mx-auto w-full max-w-3xl px-6 py-10 lg:px-12">
          <div className="mb-8">
            <p className="text-xs font-semibold tracking-wide text-brand uppercase">Workspace</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">Documents</h1>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-muted">
              Upload a PDF and StudyMind reads it, structures it, and grounds every answer,
              quiz, and interview question strictly in what you gave it, unless you tell it
              otherwise.
            </p>
          </div>

          <div className="mb-10">
            <HowItWorks />
          </div>

          <section>
            <h2 className="text-sm font-semibold tracking-tight text-ink">Upload a document</h2>
            <p className="mt-1 mb-4 text-xs text-ink-muted">
              PDF only for now. More formats are on the way.
            </p>
            <UploadDropzone onUploaded={addDocument} />
          </section>
        </main>

        <section className="mx-auto w-full max-w-5xl px-6 pb-10 lg:px-12">
          <h2 className="text-sm font-semibold tracking-tight text-ink">Your documents</h2>
          <p className="mt-1 mb-4 text-xs text-ink-muted">
            Select a document to see its overview. Add as many resources as you're studying
            from.
          </p>
          {error && (
            <p role="alert" className="mb-4 text-sm text-status-failed">
              {error}
            </p>
          )}
          <DocumentList documents={documents} isLoading={isLoading} onDeleted={removeDocument} />
        </section>
      </div>
    </div>
  );
}

function Logo() {
  return (
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="#C2660B" />
      <path
        d="M9 22V10.5C9 9.67 9.67 9 10.5 9H16v14H10.5A1.5 1.5 0 0 1 9 21.5V22Z"
        fill="#FAF8F5"
        fillOpacity="0.92"
      />
      <path d="M16 9h5.5c.83 0 1.5.67 1.5 1.5V22h-7V9Z" fill="#FAF8F5" fillOpacity="0.6" />
    </svg>
  );
}

export default App;
