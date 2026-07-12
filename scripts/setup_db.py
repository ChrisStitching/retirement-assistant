import argparse
import json
import sqlite3
from pathlib import Path


def load_settings(settings_path: Path) -> dict:
    with settings_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def resolve_settings_path(settings_arg: str | None) -> Path:
    if settings_arg:
        return Path(settings_arg)

    local_path = Path("settings.local.json")
    if local_path.exists():
        return local_path

    return Path("settings.example.json")


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def migrate_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS activity_urls (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
            url         TEXT NOT NULL,
            label       TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        )
        """
    )

    appointment_columns = _column_names(conn, "appointments")
    if "appt_end_dt" not in appointment_columns:
        conn.execute("ALTER TABLE appointments ADD COLUMN appt_end_dt TEXT")

    activity_columns = _column_names(conn, "activities")
    if "repeatability_factor" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN repeatability_factor REAL DEFAULT 2")
    if "day_of_week_mask" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN day_of_week_mask INTEGER")

    conn.execute("UPDATE activities SET repeatability_factor = 2 WHERE repeatability_factor IS NULL")


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize the retirement assistant SQLite database.")
    parser.add_argument(
        "--settings",
        default=None,
        help="Path to settings JSON file (defaults to settings.local.json, then settings.example.json).",
    )
    args = parser.parse_args()

    settings_path = resolve_settings_path(args.settings)
    settings = load_settings(settings_path)

    db_path = Path(settings["db_path"])
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)
        migrate_schema(conn)
        conn.commit()

    print(f"Database initialized at: {db_path}")
    print(f"Settings used: {settings_path}")


if __name__ == "__main__":
    main()
