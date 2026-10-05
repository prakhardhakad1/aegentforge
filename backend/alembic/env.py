"""Alembic environment for AgentForge.

Reads DATABASE_URL from the environment (falling back to app.config / the ini
value) and targets ``app.models.Base.metadata``. ``render_as_batch`` is on so
future SQLite ALTERs work.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make backend/ importable so `app` resolves (this file lives in backend/alembic/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.models import Base  # noqa: E402
import app.models  # noqa: F401,E402 - ensure all models register on Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    try:
        return get_settings().database_url
    except Exception:  # pragma: no cover - settings misconfigured
        return config.get_main_option("sqlalchemy.url") or "sqlite:///./agentforge.db"


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    config.set_main_option("sqlalchemy.url", _database_url())
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
