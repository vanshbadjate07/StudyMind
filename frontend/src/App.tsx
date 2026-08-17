import { useState } from "react";
import { ChatView } from "./components/ChatView";
import { DocumentList } from "./components/DocumentList";
import { HomeView } from "./components/HomeView";
import { HowItWorks } from "./components/HowItWorks";
import { NotebookHeader } from "./components/NotebookHeader";
import { OverviewPanel } from "./components/OverviewPanel";
import { Sidebar, type WorkspaceSection } from "./components/Sidebar";
import { UploadDropzone } from "./components/UploadDropzone";
import { useDocuments } from "./hooks/useDocuments";
import { useNotebooks } from "./hooks/useNotebooks";

function App() {
  const {
    notebooks,
    activeNotebook,
    isLoading: notebooksLoading,
    error: notebooksError,
    addNotebook,
    removeNotebook,
    renameNotebook,
    updateGoal,
    setActiveId,
  } = useNotebooks();
  const {
    documents,
    isLoading: documentsLoading,
    error: documentsError,
    addDocument,
    removeDocument,
  } = useDocuments(activeNotebook?.id ?? null);
  const [activeSection, setActiveSection] = useState<WorkspaceSection>("documents");

  const goHome = () => setActiveId(null);
  const openNotebook = (id: string) => {
    setActiveSection("documents");
    setActiveId(id);
  };

  return (
    <div className="flex h-screen overflow-hidden bg-paper">
      <Sidebar
        activeNotebook={activeNotebook}
        activeSection={activeSection}
        onSelectSection={setActiveSection}
        onGoHome={goHome}
      />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex items-center gap-2.5 border-b border-line bg-surface px-6 py-4 lg:hidden">
          <Logo />
          <div>
            <p className="text-sm font-semibold tracking-tight text-ink">StudyMind</p>
            <p className="text-xs text-ink-muted">Your material, understood.</p>
          </div>
        </header>

        {activeNotebook === null ? (
          <HomeView
            notebooks={notebooks}
            isLoading={notebooksLoading}
            error={notebooksError}
            onCreateNotebook={() => void addNotebook()}
            onOpenNotebook={openNotebook}
            onRenameNotebook={async (id, name) => {
              await renameNotebook(id, name);
            }}
            onDeleteNotebook={removeNotebook}
          />
        ) : activeSection === "chat" ? (
          <ChatView notebookId={activeNotebook.id} notebookName={activeNotebook.name} />
        ) : (
          <main className="mx-auto min-h-0 w-full max-w-3xl flex-1 overflow-y-auto px-6 py-10 lg:px-12">
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
              {documents.some((doc) => doc.status === "ready") ? (
                <OverviewPanel
                  notebookId={activeNotebook.id}
                  watchKey={documents
                    .map((doc) => `${doc.id}:${doc.status}`)
                    .sort()
                    .join(",")}
                />
              ) : (
                <HowItWorks />
              )}
            </div>

            <section className="mb-10">
              <h2 className="text-sm font-semibold tracking-tight text-ink">Upload a document</h2>
              <p className="mt-1 mb-4 text-xs text-ink-muted">
                PDF only for now. More formats are on the way.
              </p>
              <UploadDropzone notebookId={activeNotebook.id} onUploaded={addDocument} />
            </section>

            <section>
              <h2 className="text-sm font-semibold tracking-tight text-ink">Your documents</h2>
              <p className="mt-1 mb-4 text-xs text-ink-muted">
                Add as many resources as you're studying from — they're combined into one overview
                above.
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
          </main>
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
