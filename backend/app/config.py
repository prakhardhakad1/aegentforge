"""Application settings (pydantic-settings).

Everything comes from environment variables (optionally a ``backend/.env``
file when running locally). The repo-root ``.env.example`` is coordinator-owned,
so the canonical env-var documentation for the backend lives in this docstring:

    # ── Auth ────────────────────────────────────────────────────────────
    API_KEY=                        # optional; empty = guest mode (no auth required)

    # ── Runtime mode ───────────────────────────────────────────────────
    RUN_MODE=demo                   # demo | live (demo = simulated run, no LLM needed)

    # ── Storage ────────────────────────────────────────────────────────
    DATABASE_URL=sqlite:///./agentforge.db
    UPLOAD_DIR=./data/uploads       # uploaded datasets land at {UPLOAD_DIR}/{dataset_id}.csv
    MAX_UPLOAD_MB=10                # upload size cap
    REPORT_DIR=./data/reports       # (backend addition, see NOTES.md) PDF report output dir

    # ── HTTP ───────────────────────────────────────────────────────────
    CORS_ORIGINS=http://localhost:3000   # comma-separated list, "*" allowed

    # ── Token / cost meter (USD per 1M tokens) ─────────────────────────
    COST_PER_1M_INPUT_TOKENS=0.11
    COST_PER_1M_OUTPUT_TOKENS=0.11

    # ── LLM provider (provider-agnostic, OpenAI-compatible) ────────────
    LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
    LLM_API_KEY=                    # never commit a real key
    LLM_MODEL=glm-4-flash
    LLM_FALLBACK_MODEL=glm-4-flash
    LLM_MODE=mock                   # live | mock
    LLM_TIMEOUT_SECONDS=60

No value here is ever used to reach the network at import time; secrets are read
from the environment only.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend configuration, loaded from env vars / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Auth ────────────────────────────────────────────────────────────
    api_key: str = ""  # empty string disables the auth check (guest mode)

    # ── Runtime mode ────────────────────────────────────────────────────
    run_mode: Literal["demo", "live"] = "demo"

    # ── Storage ─────────────────────────────────────────────────────────
    database_url: str = "sqlite:///./agentforge.db"
    upload_dir: str = "./data/uploads"
    report_dir: str = "./data/reports"
    max_upload_mb: float = 10.0

    # ── HTTP ────────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000"

    # ── Token / cost meter (USD per 1M tokens) ──────────────────────────
    cost_per_1m_input_tokens: float = 0.11
    cost_per_1m_output_tokens: float = 0.11

    # ── LLM provider ────────────────────────────────────────────────────
    llm_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    llm_api_key: str = ""
    llm_model: str = "glm-4-flash"
    llm_fallback_model: str = "glm-4-flash"
    llm_mode: Literal["live", "mock"] = "mock"
    llm_timeout_seconds: float = 60.0

    # ── Derived helpers ─────────────────────────────────────────────────

    @property
    def cors_origin_list(self) -> list[str]:
        """Parsed CORS origin list. ``*`` short-circuits to wildcard mode."""
        raw = (self.cors_origins or "").strip()
        if not raw:
            return []
        parts = [p.strip().rstrip("/") for p in raw.split(",") if p.strip()]
        if "*" in parts:
            return ["*"]
        return parts

    @property
    def max_upload_bytes(self) -> int:
        """Upload cap expressed in bytes (MB -> bytes, floored)."""
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def auth_enabled(self) -> bool:
        """True when an API key is configured (auth enforcement on)."""
        return bool((self.api_key or "").strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the (cached) settings singleton.

    Used as a FastAPI dependency, so tests can override it via
    ``app.dependency_overrides[get_settings]``.
    """
    return Settings()
