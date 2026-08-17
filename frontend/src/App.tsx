import { DocumentList } from "./components/DocumentList";
import { HowItWorks } from "./components/HowItWorks";
import { NotebookHeader } from "./components/NotebookHeader";
import { Sidebar } from "./components/Sidebar";
import { UploadDropzone } from "./components/UploadDropzone";
import { useDocuments } from "./hooks/useDocuments";
import { useNotebooks } from "./hooks/useNotebooks";

function App() {
  const {
    notebooks,
    activeNotebook,
    activeId,
    setActiveId,
    isLoading: notebooksLoading,
    error: notebooksError,
    addNotebook,
    removeNotebook,
    renameNotebook,
    updateGoal,
  } = useNotebooks();
  const {
    documents,
    isLoading: documentsLoading,
    error: documentsError,
    addDocument,
    removeDocument,
  } = useDocuments(activeId);

  return (
    <div className="flex h-screen overflow-hidden bg-paper">
      <Sidebar
        notebooks={notebooks}
        activeNotebookId={activeId}
        notebooksLoading={notebooksLoading}
        onSelectNotebook={setActiveId}
        onCreateNotebook={() => void addNotebook()}
        onDeleteNotebook={removeNotebook}
      />

      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <header className="flex items-center gap-2.5 border-b border-line bg-surface px-6 py-4 lg:hidden">
          <Logo />
          <div>
            <p className="text-sm font-semibold tracking-tight text-ink">StudyMind</p>
            <p className="text-xs text-ink-muted">Your material, understood.</p>
          </div>
        </header>

        {notebooksError && (
          <p role="alert" className="px-6 pt-6 text-sm text-status-failed lg:px-12">
            {notebooksError}
          </p>
        )}

        {notebooksLoading ? (
          <div className="mx-auto w-full max-w-3xl px-6 py-10 lg:px-12">
            <div className="h-24 animate-pulse rounded-xl bg-line/60" />
          </div>
        ) : activeNotebook === null ? (
          <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center px-6 py-10 text-center lg:px-12">
            <p className="text-sm font-medium text-ink">No notebook yet</p>
            <p className="mt-1 max-w-sm text-sm text-ink-muted">
              A notebook groups the resources you're studying from — create one to start
              uploading documents.
            </p>
            <button
              type="button"
              onClick={() => void addNotebook()}
              className="mt-4 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-white hover:bg-brand-hover"
            >
              Create your first notebook
            </button>
          </div>
        ) : (
          <>
            <main className="mx-auto w-full max-w-3xl px-6 py-10 lg:px-12">
              <NotebookHeader
                notebook={activeNotebook}
                onSetGoal={async (goalType, description) => {
                  await updateGoal(activeNotebook.id, goalType, description);
                }}
                onRename={async (name) => {
                  await renameNotebook(activeNotebook.id, name);
                }}
              />

              <div className="mb-10">
                <HowItWorks />
              </div>

              <section>
                <h2 className="text-sm font-semibold tracking-tight text-ink">Upload a document</h2>
                <p className="mt-1 mb-4 text-xs text-ink-muted">
                  PDF only for now. More formats are on the way.
                </p>
                <UploadDropzone notebookId={activeNotebook.id} onUploaded={addDocument} />
              </section>
            </main>

            <section className="mx-auto w-full max-w-5xl px-6 pb-10 lg:px-12">
              <h2 className="text-sm font-semibold tracking-tight text-ink">Your documents</h2>
              <p className="mt-1 mb-4 text-xs text-ink-muted">
                Select a document to see its overview. Add as many resources as you're studying
                from.
              </p>
              {documentsError && (
                <p role="alert" className="mb-4 text-sm text-status-failed">
                  {documentsError}
                </p>
              )}
              <DocumentList
                documents={documents}
                isLoading={documentsLoading}
                onDeleted={removeDocument}
              />
            </section>
          </>
        )}
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
