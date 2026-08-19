from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "jobsearch"
    debug: bool = False
    log_level: str = "INFO"
    environment: Literal["local", "production"] = "local"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5434/jobsearch"
    database_echo: bool = False

    api_key: str | None = None  # single service key held by the Next.js server, checked in auth.py

    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    # any OpenAI-compatible endpoint works, e.g. https://openrouter.ai/api/v1
    # or http://localhost:11434/v1 for Ollama; None = api.openai.com
    openai_base_url: str | None = None

    match_threshold: int = 60  # minimum MatchOutput.score to land on the shortlist

    embedding_model: str = "text-embedding-3-small"  # 1536 dims — must match EMBED_DIM
    # postings kept per retrieval query, per channel (vector, full-text). This is
    # also the hard cap on how many postings ever reach the scorer, so it sets both
    # the shortlist size and the per-run LLM cost — raise it for more offers, lower
    # it for a cheaper run.
    retrieval_top_k: int = 50
    resume_context_chunks: int = 3  # resume sections handed to the scorer per posting

    # Gmail ingest: app password (needs 2FA on the account), not OAuth
    gmail_user: str | None = None
    gmail_app_password: str | None = None
    # job-alert senders to read; comma-separated in .env. NoDecode stops
    # pydantic-settings JSON-parsing the value before _split_senders sees it
    gmail_senders: Annotated[list[str], NoDecode] = []
    gmail_mailbox: str = "INBOX"
    # "trash" moves a mail to [Gmail]/Trash once its postings are stored — recoverable
    # for 30 days. "keep" only marks it read.
    gmail_after_ingest: Literal["trash", "keep"] = "trash"

    scrape_max_depth: int = 1
    scrape_max_pages: int = 20
    scrape_request_timeout_seconds: int = 30

    @field_validator("gmail_senders", mode="before")
    @classmethod
    def _split_senders(cls, value: object) -> object:
        # so .env can say GMAIL_SENDERS=a@x.com,b@y.com instead of a JSON array
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://") :]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
