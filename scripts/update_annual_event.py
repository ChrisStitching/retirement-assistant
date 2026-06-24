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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update an annual recurring event.")
    parser.add_argument("annual_event_id", type=int, help="Annual event id to update")
    parser.add_argument("--title")
    parser.add_argument("--event-date", help='YYYY-MM-DD, e.g. "2008-04-07"')
    parser.add_argument(
        "--description",
        help="Set description; pass an empty string to clear it",
    )
    parser.add_argument(
        "--reminder-days-before",
        type=int,
        help="Days before anniversary to show an advance reminder",
    )
    parser.add_argument(
        "--status",
        choices=["active", "inactive"],
        help="Set status to active or inactive",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    updates: dict[str, object] = {}
    if args.title is not None:
        title = args.title.strip()
        if not title:
            raise SystemExit("--title cannot be empty")
        updates["title"] = title

    if args.event_date is not None:
        try:
            date.fromisoformat(args.event_date)
        except ValueError as exc:
            raise SystemExit("--event-date must be in YYYY-MM-DD format") from exc
        updates["event_date"] = args.event_date

    if args.description is not None:
        updates["description"] = args.description.strip() or None

    if args.reminder_days_before is not None:
        if args.reminder_days_before < 0:
            raise SystemExit("--reminder-days-before cannot be negative")
        updates["reminder_days_before"] = args.reminder_days_before

    if args.status is not None:
        updates["status"] = args.status

    if not updates:
        raise SystemExit("Provide at least one field to update")

    db_path = load_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id
            FROM annual_events
            WHERE id = ?
            """,
            (args.annual_event_id,),
        )
        if cursor.fetchone() is None:
            raise SystemExit(f"Annual event {args.annual_event_id} not found")

        assignments = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(
            f"UPDATE annual_events SET {assignments} WHERE id = ?",
            (*updates.values(), args.annual_event_id),
        )
        conn.commit()

    print("Annual event updated.")


if __name__ == "__main__":
    main()
