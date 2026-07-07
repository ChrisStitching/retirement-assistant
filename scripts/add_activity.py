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
    parser = argparse.ArgumentParser(description="Add an activity.")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--location", default="")
    parser.add_argument("--category", default="")
    parser.add_argument("--weather-sensitive", type=int, default=0, choices=[0, 1])
    parser.add_argument("--physical-intensity", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--repeatability-factor", type=float, default=2.0)
    parser.add_argument("--url", dest="urls", action="append", default=[])
    args = parser.parse_args()

    if args.repeatability_factor <= 0:
        raise SystemExit("--repeatability-factor must be greater than 0")

    db_path = load_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO activities (
                title,
                description,
                location,
                category,
                weather_sensitive,
                physical_intensity,
                repeatability_factor
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                args.title,
                args.description or None,
                args.location or None,
                args.category or None,
                args.weather_sensitive,
                args.physical_intensity,
                args.repeatability_factor,
            ),
        )
        activity_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        urls = [url.strip() for url in args.urls if url and url.strip()]
        if urls:
            conn.executemany(
                "INSERT INTO activity_urls (activity_id, url) VALUES (?, ?)",
                [(activity_id, url) for url in urls],
            )
        conn.commit()

    print("Activity added.")



if __name__ == "__main__":
    main()
