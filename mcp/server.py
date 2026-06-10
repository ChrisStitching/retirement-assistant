from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date as date_type
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP


logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)


def _load_settings() -> dict[str, Any]:
    local_path = Path("settings.local.json")
    settings_path = local_path if local_path.exists() else Path("settings.example.json")
    return json.loads(settings_path.read_text(encoding="utf-8"))


def _db_path() -> Path:
    settings = _load_settings()
    return Path(settings["db_path"])


def _as_date(input_date: str | None) -> str:
    if input_date:
        return input_date
    return date_type.today().isoformat()


mcp = FastMCP("retirement-assistant")


@mcp.tool()
def get_daily_briefing(date: str | None = None) -> dict[str, Any]:
    """Return appointments, active timed events, and activity suggestions for a date."""

    target_date = _as_date(date)
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row

    appointments = conn.execute(
        """
        SELECT id, title, location, appt_dt, notes
        FROM appointments
        WHERE date(appt_dt) IN (date(?), date(?, '+1 day'))
        ORDER BY appt_dt ASC
        """,
        (target_date, target_date),
    ).fetchall()

    timed_events = conn.execute(
        """
        SELECT id, title, description, url, start_date, end_date, status
        FROM timed_events
        WHERE date(?) BETWEEN date(start_date) AND date(end_date)
          AND status = 'active'
        ORDER BY start_date ASC
        """,
        (target_date,),
    ).fetchall()

    suggestion_count = int(_load_settings().get("activity_suggestions_per_day", 3))
    activities = conn.execute(
        """
        SELECT a.id, a.title, a.description, a.location, a.category
        FROM activities a
        WHERE a.id NOT IN (
            SELECT activity_id
            FROM activity_log
            WHERE status = 'done' AND log_date = date(?, '-1 day')
        )
        ORDER BY random()
        LIMIT ?
        """,
        (target_date, suggestion_count),
    ).fetchall()

    conn.close()

    return {
        "date": target_date,
        "appointments": [dict(row) for row in appointments],
        "active_timed_events": [dict(row) for row in timed_events],
        "activity_suggestions": [dict(row) for row in activities],
    }


@mcp.tool()
def log_activity(activity_id: int, status: str, log_date: str | None = None, notes: str = "") -> dict[str, Any]:
    """Record an activity outcome for a given date in the activity log."""

    target_date = _as_date(log_date)

    conn = sqlite3.connect(_db_path())
    cursor = conn.execute(
        """
        INSERT INTO activity_log (activity_id, log_date, status, notes)
        VALUES (?, ?, ?, ?)
        """,
        (activity_id, target_date, status, notes or None),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "id": cursor.lastrowid}


@mcp.tool()
def add_appointment(title: str, appt_dt: str, location: str = "", notes: str = "") -> dict[str, Any]:
    """Add an appointment with ISO datetime like 2026-06-17T09:00."""

    conn = sqlite3.connect(_db_path())
    cursor = conn.execute(
        """
        INSERT INTO appointments (title, location, appt_dt, notes)
        VALUES (?, ?, ?, ?)
        """,
        (title, location or None, appt_dt, notes or None),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "id": cursor.lastrowid}


@mcp.tool()
def add_timed_event(
    title: str,
    start_date: str,
    end_date: str,
    description: str = "",
    url: str = "",
) -> dict[str, Any]:
    """Add a timed event with date range in YYYY-MM-DD format."""

    conn = sqlite3.connect(_db_path())
    cursor = conn.execute(
        """
        INSERT INTO timed_events (title, description, url, start_date, end_date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (title, description or None, url or None, start_date, end_date),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "id": cursor.lastrowid}


@mcp.tool()
def add_activity(
    title: str,
    description: str = "",
    location: str = "",
    category: str = "",
    weather_sensitive: int = 0,
    physical_intensity: int = 1,
) -> dict[str, Any]:
    """Add an activity suggestion to the activity pool."""

    conn = sqlite3.connect(_db_path())
    cursor = conn.execute(
        """
        INSERT INTO activities (
            title,
            description,
            location,
            category,
            weather_sensitive,
            physical_intensity
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            description or None,
            location or None,
            category or None,
            weather_sensitive,
            physical_intensity,
        ),
    )
    conn.commit()
    conn.close()

    return {"ok": True, "id": cursor.lastrowid}


if __name__ == "__main__":
    mcp.run()
