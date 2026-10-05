"""Versioned schema migrations (Alembic), run at boot.

How the schema is built, in order, on every cold start:

1. ``db.create_all()`` creates any missing table at the current model shape
   (a fresh database is complete after this step).
2. ``app._migrate_schema()`` — the legacy, hand-written idempotent ALTERs.
   Frozen: add nothing new there.
3. ``upgrade()`` below — Alembic revisions in ``migrations/versions``.
   Every new schema change goes here as a revision.

Because step 1 already produced the current shape on a fresh database,
revisions must be idempotent: inspect first, change only what is not yet
there (see 0002_money_numeric for the pattern).

Vercel runs many instances that can cold-start together. On Postgres the
whole upgrade runs in one transaction holding ``pg_advisory_xact_lock``, so
one instance migrates while the others wait and then find nothing to do. A
transaction-scoped lock (not a session lock) is used on purpose: it also
works through Neon's pooled (PgBouncer, transaction mode) connection string.

Manual use, against any DATABASE_URL:  ``python tools/db_migrate.py --help``
"""
import os

from alembic import command
from alembic.config import Config as AlembicConfig

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "migrations")

# Arbitrary constant shared by every instance of this app.
ADVISORY_LOCK_KEY = 815_204_117


def alembic_config(connection=None):
    cfg = AlembicConfig()
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def upgrade(engine, revision="head"):
    """Bring the database to ``revision``. Safe to call on every boot."""
    with engine.connect() as connection:
        command.upgrade(alembic_config(connection), revision)
        connection.commit()


def current(engine):
    from alembic.runtime.migration import MigrationContext
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
