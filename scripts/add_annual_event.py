import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path


def load_db_path() -> Path:
    settings_file = Path("settings.local.json")
    if not settings_file.exists():
        settings_file = Path("settings.example.json")
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    return Path(settings["db_path"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Add an annual recurring event.")
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--event-date",
        required=True,
        help='Anchor date in YYYY-MM-DD format, e.g. "2008-04-07"',
    )
    parser.add_argument("--description", default="")
    parser.add_argument(
        "--reminder-days-before",
        type=int,
        default=7,
        help="Days before anniversary to show an advance reminder (default: 7)",
    )
    args = parser.parse_args()

    if args.reminder_days_before < 0:
        raise SystemExit("--reminder-days-before cannot be negative")

    try:
        date.fromisoformat(args.event_date)
    except ValueError as exc:
        raise SystemExit("--event-date must be in YYYY-MM-DD format") from exc

    db_path = load_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO annual_events (title, event_date, description, reminder_days_before)
            VALUES (?, ?, ?, ?)
            """,
            (
                args.title,
                args.event_date,
                args.description or None,
                args.reminder_days_before,
            ),
        )
        conn.commit()

    print("Annual event added.")


if __name__ == "__main__":
    main()
