"""Wait for Postgres, then seed the database if it's empty (idempotent startup)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import inspect, text  # noqa: E402
from app.db import engine  # noqa: E402

for attempt in range(30):
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        break
    except Exception:
        print(f"Waiting for database... ({attempt + 1}/30)")
        time.sleep(2)
else:
    raise SystemExit("Database never became available")

insp = inspect(engine)
if insp.has_table("properties"):
    with engine.connect() as c:
        n = c.execute(text("SELECT COUNT(*) FROM properties")).scalar()
    if n and n > 0:
        print(f"Database already seeded ({n} properties). Skipping.")
        raise SystemExit(0)

print("Seeding database...")
import seed_db  # noqa: E402
seed_db.main()
