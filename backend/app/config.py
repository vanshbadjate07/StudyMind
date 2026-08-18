from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDYMIND_", env_file=".env", extra="ignore")

    data_dir: Path = BACKEND_DIR / "data"
    uploads_dir: Path = BACKEND_DIR / "data" / "uploads"
    presentations_dir: Path = BACKEND_DIR / "data" / "presentations"
    chroma_dir: Path = BACKEND_DIR / "data" / "chroma"
    database_url: str = f"sqlite+aiosqlite:///{BACKEND_DIR / 'data' / 'studymind.db'}"

    max_upload_bytes: int = 50 * 1024 * 1024
    # Keep in sync with app.services.extraction.extract_text's dispatch —
    # that's what actually determines what can be parsed.
    allowed_extensions: tuple[str, ...] = (".pdf", ".txt", ".md", ".docx", ".pptx")

    chunk_size_chars: int = 1000
    chunk_overlap_chars: int = 150

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    chroma_collection_name: str = "document_chunks"

    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")

    # Cloud LLM provider chain (Cerebras -> Groq -> Gemini): used in
    # production so the app doesn't depend on a locally-running Ollama
    # instance. Each provider takes a *list* of API keys, not just one — if
    # a provider has multiple keys configured (e.g. two free accounts), the
    # chain tries them in order before moving to the next provider, roughly
    # doubling that provider's effective daily quota. A provider is only
    # added to the chain if it has at least one key set; with none set at
    # all (local dev, CI), get_default_llm_client() falls back to local
    # Ollama below. llm_provider_timeout_seconds is deliberately short
    # relative to each feature's overall LLM timeout (e.g. quiz's 240s) —
    # it's a per-attempt timeout within the chain, so one slow provider/key
    # fails fast and the chain moves to the next rather than burning the
    # whole feature timeout on a single hung attempt. Set as JSON arrays in
    # .env (pydantic-settings' default parsing for tuple fields), matching
    # how cors_origins below is already set.
    cerebras_api_keys: tuple[str, ...] = ()
    cerebras_model: str = "gpt-oss-120b"
    groq_api_keys: tuple[str, ...] = ()
    groq_model: str = "openai/gpt-oss-120b"
    gemini_api_keys: tuple[str, ...] = ()
    gemini_model: str = "gemini-3.6-flash"
    llm_provider_timeout_seconds: float = 45.0

    ollama_host: str = "http://localhost:11434"
    overview_model: str = "qwen2.5:3b"
    overview_llm_timeout_seconds: float = 120.0
    # Ollama's runtime context window isn't guaranteed to match the model's
    # max capability unless requested explicitly, so num_ctx is always set on
    # every call rather than relying on Ollama's default.
    overview_context_tokens: int = 8192
    overview_single_pass_char_budget: int = 4000
    overview_target_section_chars: int = 4000
    overview_max_section_chars: int = 12000
    overview_max_sections: int = 20

    # Reuses the overview_* sizing settings above for splitting material into
    # LLM-sized sections — same chunking problem, no need for a second set of
    # tuning knobs. quiz_llm_timeout_seconds is its own setting, though:
    # generating several structured multiple-choice questions (4 options +
    # an explanation each) is a much heavier per-call output than overview's
    # "summarize in 2-4 sentences", and reusing overview's 120s timeout was
    # observed timing out on a real multi-document notebook.
    quiz_question_count: int = 8
    quiz_llm_timeout_seconds: float = 240.0

    chat_model: str = "qwen2.5:3b"
    chat_llm_timeout_seconds: float = 120.0
    chat_context_tokens: int = 8192
    chat_top_k: int = 6
    # Chroma L2 distance (embeddings are normalized, so this ranges roughly
    # 0-4). The old value here (1.3) was calibrated against wildly-different
    # topics (biology vs. basketball) which land well over 1.7 — but a
    # same-broad-domain, different-subtopic pair (e.g. a "Python looping"
    # question against "combinatorial testing" material — both CS-adjacent)
    # lands around 1.27-1.37, which slipped under 1.3 and got cited as if it
    # answered the question. Empirically, on-topic matches (exact, paraphrased,
    # or an adjacent subtopic of the same excerpt) land at ~0.46-1.10;
    # same-domain-but-unrelated content lands at ~1.27+. This sits with
    # margin on both sides of THAT gap, not the wider (and less realistic)
    # one the old value was tuned against.
    chat_relevance_distance_threshold: float = 1.15
    # How many prior messages (user + assistant combined) to include as
    # conversation context for follow-up questions.
    chat_history_messages: int = 8

    # Reuses the overview_* sizing settings for splitting material into
    # LLM-sized sections, same as quiz. A larger timeout than quiz's, since
    # a slide plan is a heavier structured output (title + subtitle/lines/
    # columns per slide across up to 30 slides) than quiz's 4-options-plus-
    # explanation shape.
    presentation_slide_count: int = 10
    presentation_llm_timeout_seconds: float = 300.0


settings = Settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.presentations_dir.mkdir(parents=True, exist_ok=True)
settings.chroma_dir.mkdir(parents=True, exist_ok=True)
