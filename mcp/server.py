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


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _normalize_urls(urls: list[str] | None) -> list[str]:
    if not urls:
        return []
    return [url.strip() for url in urls if url and url.strip()]


def _activity_urls_by_id(conn: sqlite3.Connection, activity_ids: list[int]) -> dict[int, list[str]]:
    if not activity_ids:
        return {}

    placeholders = ", ".join("?" for _ in activity_ids)
    rows = conn.execute(
        f"""
        SELECT activity_id, url
        FROM activity_urls
        WHERE activity_id IN ({placeholders})
        ORDER BY id ASC
        """,
        activity_ids,
    ).fetchall()

    urls_by_id: dict[int, list[str]] = {activity_id: [] for activity_id in activity_ids}
    for row in rows:
        urls_by_id[row["activity_id"]].append(row["url"])
    return urls_by_id


def _hydrate_activities(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    activities = [dict(row) for row in rows]
    urls_by_id = _activity_urls_by_id(conn, [activity["id"] for activity in activities])
    for activity in activities:
        activity["urls"] = urls_by_id.get(activity["id"], [])
    return activities


def _replace_activity_urls(conn: sqlite3.Connection, activity_id: int, urls: list[str]) -> None:
    conn.execute("DELETE FROM activity_urls WHERE activity_id = ?", (activity_id,))
    if urls:
        conn.executemany(
            "INSERT INTO activity_urls (activity_id, url) VALUES (?, ?)",
            [(activity_id, url) for url in urls],
        )


def _get_activity(conn: sqlite3.Connection, activity_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, title, description, location, category, weather_sensitive, physical_intensity
        FROM activities
        WHERE id = ?
        """,
        (activity_id,),
    ).fetchone()
    if row is None:
        return None

    return _hydrate_activities(conn, [row])[0]


def _find_activity_row(
    conn: sqlite3.Connection,
    activity_id: int | None = None,
    title: str | None = None,
) -> tuple[sqlite3.Row | None, list[dict[str, Any]]]:
    if activity_id is not None:
        row = conn.execute(
            """
            SELECT id, title, description, location, category, weather_sensitive, physical_intensity
            FROM activities
            WHERE id = ?
            """,
            (activity_id,),
        ).fetchone()
        return row, []

    if title is None or not title.strip():
        return None, []

    normalized_title = title.strip()
    exact_matches = conn.execute(
        """
        SELECT id, title, description, location, category, weather_sensitive, physical_intensity
        FROM activities
        WHERE lower(title) = lower(?)
        ORDER BY title COLLATE NOCASE ASC
        """,
        (normalized_title,),
    ).fetchall()
    if len(exact_matches) == 1:
        return exact_matches[0], []
    if len(exact_matches) > 1:
        return None, _hydrate_activities(conn, exact_matches)

    search_term = f"%{normalized_title}%"
    partial_matches = conn.execute(
        """
        SELECT id, title, description, location, category, weather_sensitive, physical_intensity
        FROM activities
        WHERE lower(title) LIKE lower(?)
        ORDER BY title COLLATE NOCASE ASC
        """,
        (search_term,),
    ).fetchall()
    if len(partial_matches) == 1:
        return partial_matches[0], []
    if len(partial_matches) > 1:
        return None, _hydrate_activities(conn, partial_matches)

    return None, []


def _get_activity_details(
    conn: sqlite3.Connection,
    activity_id: int | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    row, matches = _find_activity_row(conn, activity_id=activity_id, title=title)
    if row is None:
        query = title.strip() if title else activity_id
        error = f"Activity not found for {query}"
        if matches:
            error = f"Multiple activities matched {query}"
        return {"ok": False, "error": error, "matches": matches}

    activity = _hydrate_activities(conn, [row])[0]
    last_visited = conn.execute(
        """
        SELECT log_date
        FROM activity_log
        WHERE activity_id = ? AND status = 'done'
        ORDER BY log_date DESC, id DESC
        LIMIT 1
        """,
        (activity["id"],),
    ).fetchone()
    latest_log = conn.execute(
        """
        SELECT log_date, status, notes
        FROM activity_log
        WHERE activity_id = ?
        ORDER BY log_date DESC, id DESC
        LIMIT 1
        """,
        (activity["id"],),
    ).fetchone()

    return {
        "ok": True,
        "activity": {
            **activity,
            "last_visited_date": last_visited["log_date"] if last_visited else None,
            "latest_log_date": latest_log["log_date"] if latest_log else None,
            "latest_log_status": latest_log["status"] if latest_log else None,
            "latest_logged_description": latest_log["notes"] if latest_log else None,
        },
    }


def _activity_recommendation_clauses(rain_chance: int | None = None, readiness: int | None = None) -> list[str]:
    clauses: list[str] = []

    if rain_chance is not None and rain_chance > 30:
        clauses.append("a.weather_sensitive = 0")

    if readiness is not None:
        if readiness < 30:
            clauses.append("a.physical_intensity = 1")
        elif readiness < 70:
            clauses.append("a.physical_intensity IN (1, 2)")
        else:
            clauses.append("a.physical_intensity IN (2, 3)")

    return clauses


mcp = FastMCP("retirement-assistant")


@mcp.tool()
def get_daily_briefing(
    date: str | None = None,
    rain_chance: int | None = None,
    readiness: int | None = None,
) -> dict[str, Any]:
    """Return appointments, active timed events, and activity suggestions for a date."""

    target_date = _as_date(date)
    conn = _connect()

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
    recommendation_clauses = _activity_recommendation_clauses(rain_chance=rain_chance, readiness=readiness)
    recommendation_sql = ""
    if recommendation_clauses:
        recommendation_sql = "\n        AND " + "\n        AND ".join(recommendation_clauses)

    activities = conn.execute(
        f"""
        SELECT a.id, a.title, a.description, a.location, a.category, a.weather_sensitive, a.physical_intensity
        FROM activities a
        WHERE a.id NOT IN (
            SELECT activity_id
            FROM activity_log
            WHERE status = 'done' AND log_date = date(?, '-1 day')
        )
        {recommendation_sql}
        ORDER BY random()
        LIMIT ?
        """,
        (target_date, suggestion_count),
    ).fetchall()

    activity_suggestions = _hydrate_activities(conn, activities)
    conn.close()

    return {
        "date": target_date,
        "rain_chance": rain_chance,
        "readiness": readiness,
        "appointments": [dict(row) for row in appointments],
        "active_timed_events": [dict(row) for row in timed_events],
        "activity_suggestions": activity_suggestions,
    }


@mcp.tool()
def log_activity(activity_id: int, status: str, log_date: str | None = None, notes: str = "") -> dict[str, Any]:
    """Record an activity outcome for a given date in the activity log."""

    target_date = _as_date(log_date)

    conn = _connect()
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

    conn = _connect()
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

    conn = _connect()
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
    urls: list[str] | None = None,
) -> dict[str, Any]:
    """Add an activity suggestion to the activity pool."""

    conn = _connect()
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
    activity_id = cursor.lastrowid
    if activity_id is None:
        conn.close()
        return {"ok": False, "error": "Failed to create activity"}

    _replace_activity_urls(conn, activity_id, _normalize_urls(urls))
    conn.commit()
    activity = _get_activity(conn, activity_id)
    conn.close()

    return {"ok": True, "id": activity_id, "activity": activity}


@mcp.tool()
def update_activity(
    activity_id: int,
    title: str | None = None,
    description: str | None = None,
    location: str | None = None,
    category: str | None = None,
    weather_sensitive: int | None = None,
    physical_intensity: int | None = None,
    urls: list[str] | None = None,
) -> dict[str, Any]:
    """Update an existing activity. Empty strings clear text fields; passing urls replaces the URL list."""

    conn = _connect()
    existing = _get_activity(conn, activity_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Activity {activity_id} not found"}

    updates: dict[str, Any] = {}
    if title is not None:
        updates["title"] = title.strip()
    if description is not None:
        updates["description"] = description.strip() or None
    if location is not None:
        updates["location"] = location.strip() or None
    if category is not None:
        updates["category"] = category.strip() or None
    if weather_sensitive is not None:
        updates["weather_sensitive"] = weather_sensitive
    if physical_intensity is not None:
        updates["physical_intensity"] = physical_intensity

    if "title" in updates and not updates["title"]:
        conn.close()
        return {"ok": False, "error": "title cannot be empty"}

    if updates:
        assignments = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(
            f"UPDATE activities SET {assignments} WHERE id = ?",
            (*updates.values(), activity_id),
        )

    if urls is not None:
        _replace_activity_urls(conn, activity_id, _normalize_urls(urls))

    conn.commit()
    activity = _get_activity(conn, activity_id)
    conn.close()
    return {"ok": True, "activity": activity}


@mcp.tool()
def get_activity_details(activity_id: int | None = None, title: str | None = None) -> dict[str, Any]:
    """Return details for a single activity by id or title fragment."""

    if activity_id is None and (title is None or not title.strip()):
        return {"ok": False, "error": "Provide either activity_id or title"}

    conn = _connect()
    result = _get_activity_details(conn, activity_id=activity_id, title=title)
    conn.close()
    return result


if __name__ == "__main__":
    mcp.run()
