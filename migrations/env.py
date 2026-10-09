"""Alembic environment: URL comes from DATABASE_URL via app settings."""
from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.db import normalize_url
from app.models import Base

target_metadata = Base.metadata
url = normalize_url(get_settings().database_url)


def run_migrations_offline() -> None:
    """Emit SQL without a DB connection."""
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=url.startswith("sqlite"))
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
