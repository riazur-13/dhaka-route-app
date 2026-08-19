"""One-off copy of fare_submissions from the old fares.db into Postgres.

Run once, from the backend directory, after DATABASE_URL is pointed at the
Postgres instance:

    python migrate_sqlite_to_postgres.py            # copy
    python migrate_sqlite_to_postgres.py --dry-run  # report what would be copied

The old SQLite ids are deliberately not carried over. Nothing references them —
they were never exposed by the API — and reusing them would mean fighting the
BIGSERIAL sequence for no gain.

Safe to run more than once: a row is skipped when a submission with the same
distance, fare, route type and timestamp is already there. Two genuinely
identical submissions in the same second would collapse into one, which is a
better failure than silently doubling every fare average on a re-run.
"""

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

from database import close_pool, db_cursor, init_db

DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / "fares.db"


def read_sqlite_rows(sqlite_path: Path) -> list[tuple]:
    connection = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    try:
        return connection.execute(
            """
            SELECT distance_km, fare_amount, route_type, created_at
            FROM fare_submissions
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()


def migrate(sqlite_path: Path, dry_run: bool) -> int:
    rows = read_sqlite_rows(sqlite_path)
    print(f"Found {len(rows)} row(s) in {sqlite_path.name}")

    if not rows:
        return 0

    if dry_run:
        for distance_km, fare_amount, route_type, created_at in rows[:5]:
            print(f"  would copy: {distance_km} km, {fare_amount} Tk, {route_type}, {created_at}")
        if len(rows) > 5:
            print(f"  ... and {len(rows) - 5} more")
        return 0

    init_db()

    copied = 0
    with db_cursor() as cursor:
        for distance_km, fare_amount, route_type, created_at in rows:
            # SQLite wrote CURRENT_TIMESTAMP, which is UTC without a zone marker.
            # Tagging it explicitly stops Postgres from reading these as local
            # time and shifting every historical fare by the Dhaka offset.
            cursor.execute(
                """
                INSERT INTO fare_submissions (distance_km, fare_amount, route_type, created_at)
                SELECT %s, %s, %s, %s::timestamp AT TIME ZONE 'UTC'
                WHERE NOT EXISTS (
                    SELECT 1 FROM fare_submissions
                    WHERE distance_km = %s
                      AND fare_amount = %s
                      AND route_type = %s
                      AND created_at = %s::timestamp AT TIME ZONE 'UTC'
                )
                """,
                (
                    distance_km, fare_amount, route_type, created_at,
                    distance_km, fare_amount, route_type, created_at,
                ),
            )
            copied += cursor.rowcount

        cursor.execute("SELECT COUNT(*) FROM fare_submissions")
        total = cursor.fetchone()[0]

    skipped = len(rows) - copied
    print(f"Copied {copied} row(s), skipped {skipped} already present.")
    print(f"fare_submissions now holds {total} row(s).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite-path",
        type=Path,
        default=DEFAULT_SQLITE_PATH,
        help="path to the old fares.db (default: alongside this script)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be copied without writing anything",
    )
    args = parser.parse_args()

    load_dotenv()

    if not os.getenv("DATABASE_URL"):
        print("DATABASE_URL is not set. Point it at Postgres and re-run.", file=sys.stderr)
        return 1

    if not args.sqlite_path.exists():
        print(f"No SQLite database at {args.sqlite_path}; nothing to migrate.", file=sys.stderr)
        return 1

    try:
        return migrate(args.sqlite_path, args.dry_run)
    finally:
        close_pool()


if __name__ == "__main__":
    raise SystemExit(main())
