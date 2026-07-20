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


def _activities_activity_type_constraint_allows_hiking(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'activities'"
    ).fetchone()
    if row is None:
        return True

    create_sql = str(row[0] or "").lower()
    if "activity_type" not in create_sql:
        return True
    if "check" not in create_sql:
        return True
    if "activity_type is null or activity_type in" not in create_sql:
        return True
    return "'hiking'" in create_sql


def _upgrade_activities_activity_type_constraint(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
            """
            CREATE TABLE activities_new (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                title               TEXT NOT NULL,
                description         TEXT,
                location            TEXT,
                category            TEXT,
                activity_type       TEXT CHECK (activity_type IS NULL OR activity_type IN ('eatery', 'landmark', 'hiking', 'geocache', 'errand', 'cozy_task', 'scout')),
                city                TEXT,
                location_detail     TEXT,
                is_evergreen        INTEGER NOT NULL DEFAULT 1 CHECK (is_evergreen IN (0, 1)),
                status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
                weather_sensitive   INTEGER DEFAULT 0,
                physical_intensity  INTEGER DEFAULT 1,
                repeatability_factor REAL DEFAULT 2,
                day_of_week_mask    INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO activities_new (
                id, title, description, location, category, activity_type, city,
                location_detail, is_evergreen, status, weather_sensitive,
                physical_intensity, repeatability_factor, day_of_week_mask
            )
            SELECT
                id, title, description, location, category, activity_type, city,
                location_detail, is_evergreen, status, weather_sensitive,
                physical_intensity, repeatability_factor, day_of_week_mask
            FROM activities
            """
        )
        conn.execute("DROP TABLE activities")
        conn.execute("ALTER TABLE activities_new RENAME TO activities")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


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
    if "planning_disposition" not in appointment_columns:
        conn.execute("ALTER TABLE appointments ADD COLUMN planning_disposition TEXT NOT NULL DEFAULT 'optional'")

    activity_columns = _column_names(conn, "activities")
    if "repeatability_factor" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN repeatability_factor REAL DEFAULT 2")
    if "day_of_week_mask" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN day_of_week_mask INTEGER")
    if "activity_type" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN activity_type TEXT")
    if "city" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN city TEXT")
    if "location_detail" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN location_detail TEXT")
    if "is_evergreen" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN is_evergreen INTEGER NOT NULL DEFAULT 1")
    if "status" not in activity_columns:
        conn.execute("ALTER TABLE activities ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")

    if not _activities_activity_type_constraint_allows_hiking(conn):
        _upgrade_activities_activity_type_constraint(conn)

    conn.execute("UPDATE activities SET repeatability_factor = 2 WHERE repeatability_factor IS NULL")
    conn.execute("UPDATE appointments SET planning_disposition = 'optional' WHERE planning_disposition IS NULL OR trim(planning_disposition) = ''")
    conn.execute("UPDATE activities SET is_evergreen = 1 WHERE is_evergreen IS NULL")
    conn.execute("UPDATE activities SET status = 'active' WHERE status IS NULL OR trim(status) = ''")
    conn.execute(
        """
        UPDATE activities
        SET city = trim(substr(coalesce(location, ''), 1, instr(coalesce(location, '') || ',', ',') - 1))
        WHERE city IS NULL AND location IS NOT NULL
        """
    )
    conn.execute("UPDATE activities SET location_detail = location WHERE location_detail IS NULL AND location IS NOT NULL")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            description TEXT,
            status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
            created_at  TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS anchors (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            city            TEXT NOT NULL,
            location_detail TEXT,
            duration        TEXT NOT NULL CHECK (duration IN ('half_day', 'full_day')),
            template_id     INTEGER NOT NULL REFERENCES templates(id),
            status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
            created_at      TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS template_slots (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id        INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
            slot_order         INTEGER NOT NULL,
            slot_type          TEXT NOT NULL CHECK (slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout')),
            required           INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0, 1)),
            location_scope     TEXT NOT NULL DEFAULT 'anchor_city' CHECK (location_scope IN ('anchor_city', 'anywhere', 'exact_location')),
            fallback_slot_type TEXT CHECK (fallback_slot_type IS NULL OR fallback_slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout')),
            created_at         TEXT DEFAULT (datetime('now')),
            UNIQUE (template_id, slot_order)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_plans (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_date     TEXT NOT NULL UNIQUE,
            plan_state    TEXT NOT NULL DEFAULT 'active' CHECK (plan_state IN ('draft', 'active', 'checked_in')),
            anchor_source TEXT NOT NULL CHECK (anchor_source IN ('user_anchor', 'mandatory_appointment', 'multi_mandatory_appointments')),
            anchor_ref_id INTEGER,
            created_at    TEXT DEFAULT (datetime('now')),
            updated_at    TEXT DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_plan_items (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            daily_plan_id    INTEGER NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
            slot_type        TEXT NOT NULL CHECK (slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout', 'appointment', 'anchor')),
            activity_id      INTEGER REFERENCES activities(id),
            status           TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'done', 'skipped', 'canceled')),
            completion_notes TEXT,
            was_fallback     INTEGER NOT NULL DEFAULT 0 CHECK (was_fallback IN (0, 1)),
            source_type      TEXT NOT NULL DEFAULT 'template_slot' CHECK (source_type IN ('template_slot', 'appointment', 'anchor')),
            source_ref_id    INTEGER,
            created_at       TEXT DEFAULT (datetime('now'))
        )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(date(appt_dt))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_appointments_disposition_date ON appointments(planning_disposition, date(appt_dt))")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_activities_type_status_city ON activities(activity_type, status, city)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_templates_status ON templates(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_anchors_status_city ON anchors(status, city)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_plans_date ON daily_plans(plan_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_plan_items_plan ON daily_plan_items(daily_plan_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_plan_items_activity ON daily_plan_items(activity_id)")


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
        try:
            conn.executescript(schema_sql)
        except sqlite3.OperationalError as exc:
            # Legacy databases can fail here because schema.sql now includes
            # indexes on planner columns that do not exist until compatibility
            # migration runs. Apply the migration first, then replay schema.
            if "no such column" not in str(exc).lower():
                raise
            migrate_schema(conn)
            conn.executescript(schema_sql)
        migrate_schema(conn)
        conn.commit()

    print(f"Database initialized at: {db_path}")
    print(f"Settings used: {settings_path}")


if __name__ == "__main__":
    main()
