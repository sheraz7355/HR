"""Alembic migrations by hand. The app also upgrades itself on boot, so this is
for checking or for writing a new revision.

    python tools/db_migrate.py current            # revision the DB is at
    python tools/db_migrate.py upgrade            # to head
    python tools/db_migrate.py revision "add x"   # new empty revision file

Uses DATABASE_URL like the app (SQLite erp.db when unset). For Neon, prefer
the direct (unpooled) connection string for manual runs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alembic import command  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402

from shared.config import Config  # noqa: E402
from shared import db_migrate  # noqa: E402


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "revision":
        if len(argv) < 2:
            print("revision needs a message")
            return 2
        command.revision(db_migrate.alembic_config(), message=argv[1])
        return 0
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    if cmd == "current":
        print(db_migrate.current(engine) or "(none)")
    elif cmd == "upgrade":
        db_migrate.upgrade(engine, argv[1] if len(argv) > 1 else "head")
        print("now at", db_migrate.current(engine))
    else:
        print("unknown command:", cmd)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
