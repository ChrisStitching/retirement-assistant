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
        conn.commit()

    print(f"Database initialized at: {db_path}")
    print(f"Settings used: {settings_path}")


if __name__ == "__main__":
    main()
