from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STUDYMIND_", env_file=".env", extra="ignore")

    data_dir: Path = BACKEND_DIR / "data"
    uploads_dir: Path = BACKEND_DIR / "data" / "uploads"
    chroma_dir: Path = BACKEND_DIR / "data" / "chroma"
    database_url: str = f"sqlite+aiosqlite:///{BACKEND_DIR / 'data' / 'studymind.db'}"

    max_upload_bytes: int = 50 * 1024 * 1024
    allowed_extensions: tuple[str, ...] = (".pdf",)

    chunk_size_chars: int = 1000
    chunk_overlap_chars: int = 150

    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    chroma_collection_name: str = "document_chunks"

    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")


settings = Settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
settings.chroma_dir.mkdir(parents=True, exist_ok=True)
