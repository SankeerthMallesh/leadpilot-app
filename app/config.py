"""Application settings. Environment variables only; nothing is hardcoded."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration, loaded from env vars or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LeadPilot"
    app_url: str = "http://localhost:8000"
    support_email: str = "support@example.com"
    allow_remote_setup: bool = False  # first-run /setup page works only from this computer unless true
    secret_key: str = Field(min_length=32)
    token_encryption_keys: str = ""
    database_url: str = "sqlite:///./leadpilot.db"
    dry_run: bool = True
    cookie_secure: bool = False
    session_max_age: int = 8 * 3600
    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    log_level: str = "INFO"

    anthropic_api_key: str = ""
    anthropic_base_url: str = "https://api.anthropic.com"
    claude_model_main: str = "claude-sonnet-5-5"
    claude_model_fast: str = "claude-haiku-4-5-20251001"
    price_main_in_per_mtok: float = 3.0
    price_main_out_per_mtok: float = 15.0
    price_fast_in_per_mtok: float = 1.0
    price_fast_out_per_mtok: float = 5.0
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 3
    llm_rate_per_minute: int = 30
    chat_rate_per_minute: int = 20
    assistant_model: str = ""
    selfcheck_model: str = ""
    monthly_budget_usd: float = 150.0

    # --- LLM provider selection: "anthropic" (default) or "ollama" (local / self-hosted, free) ---
    llm_provider: str = "anthropic"
    assistant_provider: str = ""  # optional: use a different provider just for the AI panel

    # --- Ollama (only used when a provider is "ollama"). The SERVER calls Ollama; browsers never do. ---
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_api_key: str = ""  # optional bearer token, for Ollama behind a reverse proxy
    ollama_model: str = "llama3.1:8b"
    ollama_fast_model: str = ""  # optional smaller model for the self-check pass (empty = ollama_model)
    ollama_keep_alive: str = "30m"  # how long the model stays in memory after a request ("-1" = forever)
    ollama_num_ctx: int = 4096  # context window; size to what the app needs, bigger = slower + more RAM
    ollama_temperature: float = 0.4
    ollama_structured_temperature: float = 0.2
    ollama_top_p: float = 0.9
    ollama_repeat_penalty: float = 1.1
    ollama_num_gpu: int | None = None  # layers on GPU (empty = Ollama decides)
    ollama_num_thread: int | None = None  # CPU threads (empty = Ollama decides)
    ollama_timeout_seconds: float = 180.0  # max wait between chunks (covers a cold model load)
    ollama_connect_timeout_seconds: float = 5.0
    ollama_max_concurrency: int = 2  # simultaneous generations sent to Ollama; extras wait in line
    ollama_queue_timeout_seconds: float = 60.0  # how long a request may wait in line
    ollama_warmup: bool = True  # load the model into memory when the app starts

    # --- Operator email sending (the AI panel's Email button and "send ... to name@example.com" command) ---
    chat_email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587  # 587 = STARTTLS (Gmail default), 465 = implicit SSL
    smtp_user: str = ""
    smtp_password: str = ""  # for Gmail use an App Password, never your normal password
    smtp_from: str = ""  # optional; empty = SMTP_USER


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings object."""
    return Settings()