export function TermsContent() {
  return (
    <div className="space-y-3">
      <p>
        StudyMind is a self-hosted application. You run it on your own machine, and this
        instance is operated by you, not by a third party.
      </p>
      <p>
        You're responsible for the documents you upload and for how you use the material and
        outputs this tool generates (summaries, quizzes, interview feedback). Generated content
        may contain inaccuracies — verify anything important against your source material.
      </p>
      <p>
        This software is provided as-is, without warranty of any kind. There is no service
        uptime commitment, since it runs locally on hardware you control.
      </p>
    </div>
  );
}

export function PrivacyContent() {
  return (
    <div className="space-y-3">
      <p>
        StudyMind runs entirely on your own machine. Uploaded documents, extracted text, and
        generated overviews are stored locally in this installation's own database and file
        storage — nothing is sent to StudyMind's developers or any third-party service by
        default.
      </p>
      <p>
        Document processing (text extraction, embeddings) and structured overview generation
        run against a local language model on this machine. No document content leaves your
        device during these steps.
      </p>
      <p>
        Deleting a document removes its file, extracted text, and generated overview from local
        storage.
      </p>
    </div>
  );
}
