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
    parser = argparse.ArgumentParser(description="Update an activity.")
    parser.add_argument("activity_id", type=int)
    parser.add_argument("--title")
    parser.add_argument("--description")
    parser.add_argument("--location")
    parser.add_argument("--category")
    parser.add_argument("--weather-sensitive", type=int, choices=[0, 1])
    parser.add_argument("--physical-intensity", type=int, choices=[1, 2, 3])
    parser.add_argument("--repeatability-factor", type=float)
    parser.add_argument("--url", dest="urls", action="append")
    parser.add_argument("--clear-urls", action="store_true")
    args = parser.parse_args()

    updates: dict[str, object] = {}
    if args.title is not None:
        title = args.title.strip()
        if not title:
            raise SystemExit("--title cannot be empty")
        updates["title"] = title
    if args.description is not None:
        updates["description"] = args.description.strip() or None
    if args.location is not None:
        updates["location"] = args.location.strip() or None
    if args.category is not None:
        updates["category"] = args.category.strip() or None
    if args.weather_sensitive is not None:
        updates["weather_sensitive"] = args.weather_sensitive
    if args.physical_intensity is not None:
        updates["physical_intensity"] = args.physical_intensity
    if args.repeatability_factor is not None:
        if args.repeatability_factor <= 0:
            raise SystemExit("--repeatability-factor must be greater than 0")
        updates["repeatability_factor"] = args.repeatability_factor

    replace_urls = args.clear_urls or args.urls is not None
    urls = []
    if args.urls:
        urls = [url.strip() for url in args.urls if url and url.strip()]

    if not updates and not replace_urls:
        raise SystemExit("No changes requested. Pass one or more update flags.")

    db_path = load_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        existing = conn.execute("SELECT id FROM activities WHERE id = ?", (args.activity_id,)).fetchone()
        if existing is None:
            raise SystemExit(f"Activity {args.activity_id} not found")

        if updates:
            assignments = ", ".join(f"{column} = ?" for column in updates)
            conn.execute(
                f"UPDATE activities SET {assignments} WHERE id = ?",
                (*updates.values(), args.activity_id),
            )

        if replace_urls:
            conn.execute("DELETE FROM activity_urls WHERE activity_id = ?", (args.activity_id,))
            if urls:
                conn.executemany(
                    "INSERT INTO activity_urls (activity_id, url) VALUES (?, ?)",
                    [(args.activity_id, url) for url in urls],
                )

        conn.commit()

    print("Activity updated.")


if __name__ == "__main__":
    main()