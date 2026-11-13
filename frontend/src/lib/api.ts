export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

export interface DocumentRecord {
  id: string;
  notebook_id: string;
  filename: string;
  status: DocumentStatus;
  page_count: number | null;
  char_count: number | null;
  chunk_count: number | null;
  error_reason: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
}

export type OverviewStatus = "pending" | "generating" | "ready" | "failed";

export interface TopicSummary {
  title: string;
  summary: string;
  key_concepts: string[];
}

export interface OverviewRecord {
  id: string;
  notebook_id: string;
  status: OverviewStatus;
  short_summary: string | null;
  topics: TopicSummary[];
  estimated_minutes: number | null;
  error_reason: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
}

export type QuizStatus = "pending" | "generating" | "ready" | "failed";
export type QuizDifficulty = "easy" | "medium" | "hard" | "mixed";

export interface QuizGenerateOptions {
  question_count: number;
  difficulty: QuizDifficulty;
  allow_general_knowledge: boolean;
  focus?: string;
}

export interface QuizQuestionRecord {
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
}

export interface QuizRecord {
  id: string;
  notebook_id: string;
  status: QuizStatus;
  questions: QuizQuestionRecord[];
  error_reason: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
}

export type PresentationStatus = "pending" | "generating" | "ready" | "failed";
export type PresentationStyle = "concise" | "exam_focused" | "visual_heavy";

export interface PresentationGenerateOptions {
  slide_count: number;
  style: PresentationStyle;
  focus?: string;
}

export interface PresentationRecord {
  id: string;
  notebook_id: string;
  status: PresentationStatus;
  slide_count: number | null;
  style: string | null;
  focus: string | null;
  error_reason: string | null;
  error_detail: string | null;
  created_at: string;
  updated_at: string;
}


export type InterviewMode = "text" | "voice";
export type InterviewSessionStatus = "in_progress" | "completed";

export interface InterviewTurnRecord {
  id: string;
  question_index: number;
  topic: string | null;
  question: string;
  /** True when this question re-probes a topic the previous answer scored
   * poorly on. Surfaced in the UI so the adaptation is visible rather than
   * claimed. */
  is_probe: boolean;
  answer_text: string | null;
  score: number | null;
  feedback: string | null;
  missed_points: string[];
  /** The scoring model's feature breakdown, so a score can be explained
   * rather than just asserted. */
  features: Record<string, number>;
  /** Withheld by the API until the turn has been answered. */
  ideal_answer: string | null;
  key_concepts: string[];
  asked_at: string;
  answered_at: string | null;
}

export interface InterviewSessionRecord {
  id: string;
  notebook_id: string;
  mode: InterviewMode;
  status: InterviewSessionStatus;
  question_limit: number;
  overall_score: number | null;
  weak_areas: string[];
  topics: string[];
  turns: InterviewTurnRecord[];
  current_question: InterviewTurnRecord | null;
  answered_count: number;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface InterviewStartOptions {
  mode: InterviewMode;
  question_limit: number;
  focus?: string;
}

export interface ScoringMetricsRecord {
  held_out_mae: number | null;
  held_out_r2: number | null;
  model: string | null;
  corpus_size: number | null;
  using_fallback: boolean;
}

export type GoalType = "exam" | "interview" | "skill" | "exploration" | "custom";

export interface NotebookRecord {
  id: string;
  name: string;
  goal_type: GoalType | null;
  goal_description: string | null;
  created_at: string;
  updated_at: string;
}

export type ChatRole = "user" | "assistant";

export interface ChatCitation {
  document_id: string;
  filename: string;
  page_number: number | null;
}

export interface ChatMessageRecord {
  id: string;
  role: ChatRole;
  content: string;
  citations: ChatCitation[];
  grounded: boolean;
  used_internet: boolean;
  created_at: string;
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Response body wasn't JSON; fall back to statusText.
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}

export async function listNotebooks(): Promise<NotebookRecord[]> {
  const response = await fetch(`${API_BASE_URL}/notebooks`);
  const data = await handleResponse<{ notebooks: NotebookRecord[] }>(response);
  return data.notebooks;
}

export async function createNotebook(name?: string): Promise<NotebookRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return handleResponse<NotebookRecord>(response);
}

export async function deleteNotebook(id: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${id}`, { method: "DELETE" });
  await handleResponse<void>(response);
}

export async function renameNotebook(id: string, name: string): Promise<NotebookRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  return handleResponse<NotebookRecord>(response);
}

export async function setNotebookGoal(
  id: string,
  goalType: GoalType,
  goalDescription?: string,
): Promise<NotebookRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${id}/goal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ goal_type: goalType, goal_description: goalDescription }),
  });
  return handleResponse<NotebookRecord>(response);
}

export async function listNotebookDocuments(notebookId: string): Promise<DocumentRecord[]> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/documents`);
  const data = await handleResponse<{ documents: DocumentRecord[] }>(response);
  return data.documents;
}

export async function getDocument(id: string): Promise<DocumentRecord> {
  const response = await fetch(`${API_BASE_URL}/documents/${id}`);
  return handleResponse<DocumentRecord>(response);
}

export async function deleteDocument(id: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/documents/${id}`, { method: "DELETE" });
  await handleResponse<void>(response);
}

/** One combined overview per notebook (synthesized across all of its ready
 * documents), not one per document — matches how the notebook is treated as
 * a single body of study material everywhere else. Returns null if the
 * overview hasn't started yet (e.g. no document is ready) — the backend
 * returns 404 for that case, which isn't an error here, just a "not yet" state. */
export async function getNotebookOverview(notebookId: string): Promise<OverviewRecord | null> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/overview`);
  if (response.status === 404) {
    return null;
  }
  return handleResponse<OverviewRecord>(response);
}

export async function regenerateNotebookOverview(notebookId: string): Promise<OverviewRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/overview/regenerate`, {
    method: "POST",
  });
  return handleResponse<OverviewRecord>(response);
}

/** Unlike the overview, a quiz is never generated automatically — it's
 * always the user clicking "Generate". Returns null before that first
 * click (the backend returns 404 for that case). */
export async function getNotebookQuiz(notebookId: string): Promise<QuizRecord | null> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/quiz`);
  if (response.status === 404) {
    return null;
  }
  return handleResponse<QuizRecord>(response);
}

export async function generateNotebookQuiz(
  notebookId: string,
  options: QuizGenerateOptions,
): Promise<QuizRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/quiz/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  return handleResponse<QuizRecord>(response);
}

/** Like the quiz, a presentation is only ever generated by an explicit user
 * action, so this returns null until the first generate() call (the backend
 * answers 404 for a notebook that has never had one). */
export async function getNotebookPresentation(
  notebookId: string,
): Promise<PresentationRecord | null> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/presentation`);
  if (response.status === 404) {
    return null;
  }
  return handleResponse<PresentationRecord>(response);
}

export async function generateNotebookPresentation(
  notebookId: string,
  options: PresentationGenerateOptions,
): Promise<PresentationRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/presentation/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  return handleResponse<PresentationRecord>(response);
}

/** The .pptx is served as a file download rather than fetched as JSON, so the
 * UI points a link/anchor at this URL instead of going through fetch — that
 * keeps the browser's own download handling (filename, progress) intact. */
export function presentationDownloadUrl(notebookId: string): string {
  return `${API_BASE_URL}/notebooks/${notebookId}/presentation/download`;
}

export async function listChatMessages(notebookId: string): Promise<ChatMessageRecord[]> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/chat/messages`);
  const data = await handleResponse<{ messages: ChatMessageRecord[] }>(response);
  return data.messages;
}

export async function askChatQuestion(
  notebookId: string,
  question: string,
  internetMode: boolean,
): Promise<ChatMessageRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/chat/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, internet_mode: internetMode }),
  });
  return handleResponse<ChatMessageRecord>(response);
}

export async function editChatQuestion(
  notebookId: string,
  messageId: string,
  question: string,
  internetMode: boolean,
): Promise<ChatMessageRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/chat/messages/${messageId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, internet_mode: internetMode }),
  });
  return handleResponse<ChatMessageRecord>(response);
}

/** Uses XMLHttpRequest instead of fetch so we can report upload progress —
 * fetch has no cross-browser-reliable way to observe request body progress. */
export function uploadDocument(
  notebookId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<DocumentRecord> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/notebooks/${notebookId}/documents`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      let body: unknown;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        body = undefined;
      }

      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as DocumentRecord);
        return;
      }

      const detail =
        body && typeof body === "object" && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : xhr.statusText || "Upload failed";
      reject(new ApiError(xhr.status, detail));
    };

    xhr.onerror = () => reject(new ApiError(0, "Network error. Is the server running?"));

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}


/** The notebook's most recent interview, finished or in progress. Returns
 * null before the first one (the backend answers 404 for that), same
 * convention as the overview, quiz and presentation readers above. */
export async function getNotebookInterview(
  notebookId: string,
): Promise<InterviewSessionRecord | null> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/interview`);
  if (response.status === 404) {
    return null;
  }
  return handleResponse<InterviewSessionRecord>(response);
}

export async function startNotebookInterview(
  notebookId: string,
  options: InterviewStartOptions,
): Promise<InterviewSessionRecord> {
  const response = await fetch(`${API_BASE_URL}/notebooks/${notebookId}/interview/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  return handleResponse<InterviewSessionRecord>(response);
}

/** Scores the pending answer and returns the whole session, next question
 * included. The full session rather than just the new turn, so the client
 * never has to merge state - one response is the complete truth about where
 * the interview stands. */
export async function submitInterviewAnswer(
  interviewId: string,
  answer: string,
): Promise<InterviewSessionRecord> {
  const response = await fetch(`${API_BASE_URL}/interview/${interviewId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answer }),
  });
  return handleResponse<InterviewSessionRecord>(response);
}

/** Asks the next question for a session left with none pending - the
 * recovery path when question generation failed after the previous answer
 * was already scored and saved. */
export async function continueInterview(interviewId: string): Promise<InterviewSessionRecord> {
  const response = await fetch(`${API_BASE_URL}/interview/${interviewId}/continue`, {
    method: "POST",
  });
  return handleResponse<InterviewSessionRecord>(response);
}

export async function endInterview(interviewId: string): Promise<InterviewSessionRecord> {
  const response = await fetch(`${API_BASE_URL}/interview/${interviewId}/end`, { method: "POST" });
  return handleResponse<InterviewSessionRecord>(response);
}

/** The scoring model's held-out metrics, so the UI can state how the scorer
 * performs instead of presenting its numbers as self-evident. */
export async function getScoringMetrics(): Promise<ScoringMetricsRecord> {
  const response = await fetch(`${API_BASE_URL}/interview/meta/scoring`);
  return handleResponse<ScoringMetricsRecord>(response);
}
