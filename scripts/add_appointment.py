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
    parser = argparse.ArgumentParser(description="Add an appointment.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--appt-dt", required=True, help='ISO 8601 datetime, e.g. "2026-06-17T09:00"')
    parser.add_argument("--appt-end-dt", default="", help='Optional ISO 8601 end datetime, e.g. "2026-06-17T10:00"')
    parser.add_argument("--location", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    db_path = load_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO appointments (title, location, appt_dt, appt_end_dt, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                args.title,
                args.location or None,
                args.appt_dt,
                args.appt_end_dt or None,
                args.notes or None,
            ),
        )
        conn.commit()

    print("Appointment added.")


if __name__ == "__main__":
    main()
