"""Rebuild the reporting table (gl_daily_balances) from the posted ledger.

    python tools/rebuild_gl_summary.py            # every company
    python tools/rebuild_gl_summary.py 3          # company id 3

Uses DATABASE_URL like the app. Only needed if Books Integrity reports
"Reporting table matches the ledger" as failing (e.g. after rows were
changed with raw SQL outside the app).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine  # noqa: E402

from shared.config import Config  # noqa: E402
import shared.models.ledger  # noqa: E402,F401
from shared.gl_summary import rebuild  # noqa: E402

if __name__ == "__main__":
    cid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
    with engine.begin() as conn:
        rebuild(conn, company_id=cid)
    print("Rebuilt gl_daily_balances", f"for company {cid}" if cid else "for every company")
