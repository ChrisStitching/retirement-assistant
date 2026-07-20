from __future__ import annotations

import sqlite3


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {row[0] for row in rows}


def test_fresh_schema_contains_planner_tables_and_columns(isolated_server):
    _server, db_path = isolated_server

    with sqlite3.connect(db_path) as conn:
        tables = _table_names(conn)
        assert "templates" in tables
        assert "anchors" in tables
        assert "template_slots" in tables
        assert "daily_plans" in tables
        assert "daily_plan_items" in tables

        appointment_columns = _table_columns(conn, "appointments")
        assert "planning_disposition" in appointment_columns

        activity_columns = _table_columns(conn, "activities")
        assert "activity_type" in activity_columns
        assert "city" in activity_columns
        assert "location_detail" in activity_columns
        assert "is_evergreen" in activity_columns
        assert "status" in activity_columns


def test_runtime_migration_upgrades_legacy_schema(server_module, tmp_path, monkeypatch):
    db_path = tmp_path / "legacy_retirement_assistant.db"

    legacy_sql = """
    PRAGMA foreign_keys = ON;

    CREATE TABLE appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        location TEXT,
        appt_dt TEXT NOT NULL,
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE timed_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        url TEXT,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE annual_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        event_date TEXT NOT NULL,
        description TEXT,
        reminder_days_before INTEGER DEFAULT 7,
        status TEXT DEFAULT 'active',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        location TEXT,
        category TEXT,
        weather_sensitive INTEGER DEFAULT 0,
        physical_intensity INTEGER DEFAULT 1
    );

    CREATE TABLE activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id INTEGER REFERENCES activities(id),
        log_date TEXT NOT NULL,
        status TEXT,
        notes TEXT
    );
    """

    with sqlite3.connect(db_path) as conn:
        conn.executescript(legacy_sql)
        conn.commit()

    monkeypatch.setattr(server_module, "_db_path", lambda: db_path)
    monkeypatch.setattr(
        server_module,
        "_load_settings",
        lambda: {
            "activity_suggestions_per_day": 3,
            "briefing_lookback_days": 7,
            "weather": {"enabled": False},
        },
    )
    monkeypatch.setattr(server_module, "_fetch_weather_for_date", lambda _target_date: None)

    # Any runtime DB connect should apply compatibility migration.
    conn = server_module._connect()
    conn.close()

    with sqlite3.connect(db_path) as migrated:
        tables = _table_names(migrated)
        assert "activity_urls" in tables
        assert "templates" in tables
        assert "anchors" in tables
        assert "template_slots" in tables
        assert "daily_plans" in tables
        assert "daily_plan_items" in tables

        appointment_columns = _table_columns(migrated, "appointments")
        assert "appt_end_dt" in appointment_columns
        assert "planning_disposition" in appointment_columns

        activity_columns = _table_columns(migrated, "activities")
        assert "repeatability_factor" in activity_columns
        assert "day_of_week_mask" in activity_columns
        assert "activity_type" in activity_columns
        assert "city" in activity_columns
        assert "location_detail" in activity_columns
        assert "is_evergreen" in activity_columns
        assert "status" in activity_columns


def test_runtime_migration_upgrades_old_activity_type_check_constraint(server_module, tmp_path, monkeypatch):
    db_path = tmp_path / "legacy_activity_type_check.db"

    old_constraint_sql = """
    PRAGMA foreign_keys = ON;

    CREATE TABLE appointments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        location TEXT,
        appt_dt TEXT NOT NULL,
        appt_end_dt TEXT,
        planning_disposition TEXT NOT NULL DEFAULT 'optional',
        notes TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE activities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        location TEXT,
        category TEXT,
        activity_type TEXT CHECK (activity_type IS NULL OR activity_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout')),
        city TEXT,
        location_detail TEXT,
        is_evergreen INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'active',
        weather_sensitive INTEGER DEFAULT 0,
        physical_intensity INTEGER DEFAULT 1,
        repeatability_factor REAL DEFAULT 2,
        day_of_week_mask INTEGER
    );

    CREATE TABLE activity_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id INTEGER REFERENCES activities(id),
        log_date TEXT NOT NULL,
        status TEXT,
        notes TEXT
    );
    """

    with sqlite3.connect(db_path) as conn:
        conn.executescript(old_constraint_sql)
        conn.commit()

    monkeypatch.setattr(server_module, "_db_path", lambda: db_path)
    monkeypatch.setattr(
        server_module,
        "_load_settings",
        lambda: {
            "activity_suggestions_per_day": 3,
            "briefing_lookback_days": 7,
            "weather": {"enabled": False},
        },
    )
    monkeypatch.setattr(server_module, "_fetch_weather_for_date", lambda _target_date: None)

    conn = server_module._connect()
    conn.close()

    inserted = server_module.add_activity(title="Hiking test", activity_type="hiking")
    assert inserted["ok"] is True
    assert inserted["activity"]["activity_type"] == "hiking"
