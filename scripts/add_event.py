import argparse
import json
import sqlite3
from pathlib import Path


def load_db_path() -> Path:
    settings_file = Path("settings.local.json")
    if not settings_file.exists():
        settings_file = Path("settings.example.json")
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    return Path(settings["db_path"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a timed event.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--start-date", required=True, help='YYYY-MM-DD, e.g. "2026-06-23"')
    parser.add_argument("--end-date", required=True, help='YYYY-MM-DD, e.g. "2026-06-28"')
    parser.add_argument("--description", default="")
    parser.add_argument("--url", default="")
    args = parser.parse_args()

    db_path = load_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO timed_events (title, description, url, start_date, end_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (args.title, args.description or None, args.url or None, args.start_date, args.end_date),
        )
        conn.commit()

    print("Timed event added.")


if __name__ == "__main__":
    main()
