import { useState } from "react";
import { ChatView } from "./components/ChatView";
import { DocumentList } from "./components/DocumentList";
import { HomeView } from "./components/HomeView";
import { InterviewView } from "./components/InterviewView";
import { HowItWorks } from "./components/HowItWorks";
import { NotebookHeader } from "./components/NotebookHeader";
import { OverviewPanel } from "./components/OverviewPanel";
import { QuizView } from "./components/QuizView";
import { MobileNav, Sidebar, type WorkspaceSection } from "./components/Sidebar";
import { SlidesView } from "./components/SlidesView";
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
    refresh: refreshNotebooks,
  } = useNotebooks();
  const {
    documents,
    isLoading: documentsLoading,
    error: documentsError,
    addDocument,
    removeDocument,
  } = useDocuments(activeNotebook?.id ?? null);
  const [activeSection, setActiveSection] = useState<WorkspaceSection>("documents");
  const [isNavOpen, setIsNavOpen] = useState(false);

  const goHome = () => {
    setActiveId(null);
    void refreshNotebooks();
  };
  const openNotebook = (id: string) => {
    setActiveSection("documents");
    setActiveId(id);
  };
  const createNotebook = () => {
    setActiveSection("documents");
    void addNotebook();
  };

  return (
    <div className="flex h-screen overflow-hidden bg-paper">
      <Sidebar
        activeNotebook={activeNotebook}
        activeSection={activeSection}
        onSelectSection={setActiveSection}
        onGoHome={goHome}
      />

      <MobileNav
        open={isNavOpen}
        onClose={() => setIsNavOpen(false)}
        activeNotebook={activeNotebook}
        activeSection={activeSection}
        onSelectSection={setActiveSection}
        onGoHome={goHome}
      />

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="flex items-center gap-3 border-b border-line bg-surface px-4 py-3 sm:px-6 lg:hidden">
          {/* The menu button only appears with a notebook open, because the
              drawer's only navigation is the workspace nav - on the home
              screen it would open an empty panel. */}
          {activeNotebook !== null && (
            <button
              type="button"
              onClick={() => setIsNavOpen(true)}
              aria-label="Open navigation"
              aria-expanded={isNavOpen}
              className="-ml-1 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-paper hover:text-ink"
            >
              <MenuIcon />
            </button>
          )}
          <button
            type="button"
            onClick={goHome}
            className="flex min-w-0 items-center gap-2.5 text-left"
          >
            <Logo />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold tracking-tight text-ink">
                {activeNotebook?.name ?? "StudyMind"}
              </p>
              <p className="truncate text-xs text-ink-muted">
                {activeNotebook === null ? "Your material, understood." : SECTION_LABELS[activeSection]}
              </p>
            </div>
          </button>
        </header>

        {activeNotebook === null ? (
          <HomeView
            notebooks={notebooks}
            isLoading={notebooksLoading}
            error={notebooksError}
            onCreateNotebook={createNotebook}
            onOpenNotebook={openNotebook}
            onRenameNotebook={async (id, name) => {
              await renameNotebook(id, name);
            }}
            onDeleteNotebook={removeNotebook}
          />
        ) : activeSection === "chat" ? (
          <ChatView
            notebookId={activeNotebook.id}
            notebookName={activeNotebook.name}
            hasDocuments={documents.some((doc) => doc.status === "ready")}
          />
        ) : activeSection === "quiz" ? (
          <QuizView
            notebookId={activeNotebook.id}
            notebookName={activeNotebook.name}
            hasDocuments={documents.some((doc) => doc.status === "ready")}
          />
        ) : activeSection === "slides" ? (
          <SlidesView
            notebookId={activeNotebook.id}
            notebookName={activeNotebook.name}
            hasDocuments={documents.some((doc) => doc.status === "ready")}
          />
        ) : activeSection === "interview" ? (
          <InterviewView
            notebookId={activeNotebook.id}
            notebookName={activeNotebook.name}
            hasDocuments={documents.some((doc) => doc.status === "ready")}
          />
        ) : (
          // The scroll container spans the full width so the wheel/trackpad
          // can scroll from anywhere over this pane, not just when the
          // cursor happens to be over the centered column — centering
          // (max-w-3xl mx-auto) lives on the inner wrapper instead. Putting
          // both on one element (as this used to) meant the scrollable DOM
          // node itself was only as wide as the centered column, so moving
          // the mouse into the side margins took it off that element
          // entirely and scrolling silently stopped working.
          <main className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-6 sm:py-10 lg:px-12">
            <div className="mx-auto w-full max-w-3xl">
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
                    onOverviewSettled={() => void refreshNotebooks()}
                  />
                ) : (
                  <HowItWorks />
                )}
              </div>

              <section className="mb-10">
                <h2 className="text-sm font-semibold tracking-tight text-ink">Upload a document</h2>
                <p className="mt-1 mb-4 text-xs text-ink-muted">PDF, Word, PowerPoint, or plain text.</p>
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
            </div>
          </main>
        )}
      </div>
    </div>
  );
}

const SECTION_LABELS: Record<WorkspaceSection, string> = {
  documents: "Documents",
  chat: "Chat",
  quiz: "Quiz",
  slides: "Slides",
  interview: "Interview",
};

function MenuIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      className="h-5 w-5"
    >
      <path strokeLinecap="round" d="M4 7h16M4 12h16M4 17h16" />
    </svg>
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
