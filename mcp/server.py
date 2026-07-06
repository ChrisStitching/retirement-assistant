from __future__ import annotations

import json
import logging
import ssl
import sqlite3
import calendar
from datetime import date as date_type
from datetime import datetime as datetime_type
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

try:
    import certifi
except ImportError:
    certifi = None

from mcp.server.fastmcp import FastMCP


logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)


def _load_settings() -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parent.parent
    local_candidates = [Path("settings.local.json"), repo_root / "settings.local.json"]
    example_candidates = [Path("settings.example.json"), repo_root / "settings.example.json"]

    settings_path: Path | None = None
    for candidate in local_candidates:
        if candidate.exists():
            settings_path = candidate
            break

    if settings_path is None:
        for candidate in example_candidates:
            if candidate.exists():
                settings_path = candidate
                break

    if settings_path is None:
        raise FileNotFoundError("Unable to locate settings.local.json or settings.example.json")

    return json.loads(settings_path.read_text(encoding="utf-8"))


def _db_path() -> Path:
    settings = _load_settings()
    return Path(settings["db_path"])


def _as_date(input_date: str | None) -> str:
    if input_date:
        return input_date
    return date_type.today().isoformat()


def _parse_iso_date(value: str) -> date_type:
    return date_type.fromisoformat(value)


def _parse_iso_datetime(value: str) -> datetime_type:
    return datetime_type.fromisoformat(value)


def _validate_appointment_datetimes(appt_dt: str, appt_end_dt: str | None = None) -> str | None:
    try:
        start = _parse_iso_datetime(appt_dt)
    except ValueError:
        return "appt_dt must be ISO 8601 like 2026-06-17T09:00"

    if appt_end_dt:
        try:
            end = _parse_iso_datetime(appt_end_dt)
        except ValueError:
            return "appt_end_dt must be ISO 8601 like 2026-06-17T10:00"
        if end < start:
            return "appt_end_dt must be on or after appt_dt"

    return None


def _validate_date_range(start_date: str, end_date: str, start_label: str = "start_date", end_label: str = "end_date") -> str | None:
    try:
        start = _parse_iso_date(start_date)
    except ValueError:
        return f"{start_label} must be YYYY-MM-DD"

    try:
        end = _parse_iso_date(end_date)
    except ValueError:
        return f"{end_label} must be YYYY-MM-DD"

    if end < start:
        return f"{end_label} must be on or after {start_label}"

    return None


def _anniversary_date_for_year(anchor_date: date_type, target_year: int) -> date_type:
    month = anchor_date.month
    day = anchor_date.day
    max_day = calendar.monthrange(target_year, month)[1]
    if day > max_day:
        day = max_day
    return date_type(target_year, month, day)


def _annual_reminders_for_date(conn: sqlite3.Connection, target_date: str) -> list[dict[str, Any]]:
    target = _parse_iso_date(target_date)

    rows = conn.execute(
        """
        SELECT id, title, event_date, description, reminder_days_before, status
        FROM annual_events
        WHERE status = 'active'
        ORDER BY title COLLATE NOCASE ASC
        """
    ).fetchall()

    reminders: list[dict[str, Any]] = []
    for row in rows:
        anchor = _parse_iso_date(row["event_date"])
        reminder_days_before = int(row["reminder_days_before"] or 0)
        anniversary_this_year = _anniversary_date_for_year(anchor, target.year)

        if target == anniversary_this_year:
            years = anniversary_this_year.year - anchor.year
            reminders.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "description": row["description"],
                    "event_date": row["event_date"],
                    "anniversary_date": anniversary_this_year.isoformat(),
                    "days_until": 0,
                    "years": years,
                    "kind": "anniversary_today",
                    "message": f"Today is {row['title']} ({years} years).",
                }
            )
            continue

        next_anniversary = anniversary_this_year
        if target > anniversary_this_year:
            next_anniversary = _anniversary_date_for_year(anchor, target.year + 1)

        days_until = (next_anniversary - target).days
        if days_until == reminder_days_before:
            years = next_anniversary.year - anchor.year
            reminders.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "description": row["description"],
                    "event_date": row["event_date"],
                    "anniversary_date": next_anniversary.isoformat(),
                    "days_until": days_until,
                    "years": years,
                    "kind": "anniversary_upcoming",
                    "message": f"{row['title']} is in {days_until} days ({years} years on {next_anniversary.isoformat()}).",
                }
            )

    reminders.sort(key=lambda reminder: (reminder["days_until"], reminder["title"].lower()))
    return reminders


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate_schema(conn)
    return conn


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _migrate_schema(conn: sqlite3.Connection) -> None:
    appointment_columns = _column_names(conn, "appointments")
    if "appt_end_dt" not in appointment_columns:
        conn.execute("ALTER TABLE appointments ADD COLUMN appt_end_dt TEXT")
        conn.commit()


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


def _get_appointment(conn: sqlite3.Connection, appointment_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, title, location, appt_dt, appt_end_dt, notes
        FROM appointments
        WHERE id = ?
        """,
        (appointment_id,),
    ).fetchone()
    if row is None:
        return None

    return dict(row)


def _get_timed_event(conn: sqlite3.Connection, timed_event_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, title, description, url, start_date, end_date, status
        FROM timed_events
        WHERE id = ?
        """,
        (timed_event_id,),
    ).fetchone()
    if row is None:
        return None

    return dict(row)


def _get_annual_event(conn: sqlite3.Connection, annual_event_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, title, event_date, description, reminder_days_before, status
        FROM annual_events
        WHERE id = ?
        """,
        (annual_event_id,),
    ).fetchone()
    if row is None:
        return None

    return dict(row)


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


def _activity_recommendation_clauses(
    rain_chance: int | None = None,
    readiness: int | None = None,
    temp_f_high: float | None = None,
) -> list[str]:
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

    if temp_f_high is not None:
        if temp_f_high < 55:
            clauses.append("lower(coalesce(a.category, '')) != 'motorcycle'")
        if temp_f_high > 75:
            clauses.append("a.physical_intensity != 3")
        if temp_f_high > 85:
            clauses.append("NOT (a.physical_intensity = 2 AND a.weather_sensitive = 1)")

    return clauses


def _fetch_weather_for_date(target_date: str) -> dict[str, Any] | None:
    settings = _load_settings()
    weather_settings = settings.get("weather")
    if not isinstance(weather_settings, dict):
        return None

    if not bool(weather_settings.get("enabled", False)):
        return None

    latitude = weather_settings.get("latitude")
    longitude = weather_settings.get("longitude")
    if latitude is None or longitude is None:
        return None

    try:
        params = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "timezone": str(weather_settings.get("timezone") or "auto"),
            "daily": "precipitation_probability_max,temperature_2m_max,temperature_2m_min",
            "start_date": target_date,
            "end_date": target_date,
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
        ssl_context = (
            ssl.create_default_context(cafile=certifi.where())
            if certifi is not None
            else ssl.create_default_context()
        )
        with urlopen(url, timeout=8, context=ssl_context) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        if certifi is None:
            logging.warning("Weather lookup failed (certifi not installed): %s", exc)
        else:
            logging.warning("Weather lookup failed: %s", exc)
        return None

    daily = payload.get("daily")
    if not isinstance(daily, dict):
        return None

    times = daily.get("time")
    if not isinstance(times, list) or target_date not in times:
        return None

    date_index = times.index(target_date)

    def _value_at(values: Any, index: int) -> float | None:
        if not isinstance(values, list) or index >= len(values):
            return None
        raw_value = values[index]
        if raw_value is None:
            return None
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return None

    rain_chance = _value_at(daily.get("precipitation_probability_max"), date_index)
    temp_c_max = _value_at(daily.get("temperature_2m_max"), date_index)
    temp_c_min = _value_at(daily.get("temperature_2m_min"), date_index)

    return {
        "source": "open-meteo",
        "rain_chance": int(round(rain_chance)) if rain_chance is not None else None,
        "temperature_c_max": round(temp_c_max, 1) if temp_c_max is not None else None,
        "temperature_c_min": round(temp_c_min, 1) if temp_c_min is not None else None,
        "temperature_f_max": round((temp_c_max * 9 / 5) + 32, 1) if temp_c_max is not None else None,
        "temperature_f_min": round((temp_c_min * 9 / 5) + 32, 1) if temp_c_min is not None else None,
    }


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
        SELECT id, title, location, appt_dt, appt_end_dt, notes
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

    annual_reminders = _annual_reminders_for_date(conn, target_date)

    settings = _load_settings()
    weather = _fetch_weather_for_date(target_date)
    effective_rain_chance = rain_chance if rain_chance is not None else (weather or {}).get("rain_chance")
    temp_f_high = (weather or {}).get("temperature_f_max")

    suggestion_count = int(settings.get("activity_suggestions_per_day", 3))
    lookback_days = int(settings.get("briefing_lookback_days", 7))
    if lookback_days < 1:
        lookback_days = 1
    lookback_window_days = lookback_days - 1
    recommendation_clauses = _activity_recommendation_clauses(
        rain_chance=effective_rain_chance,
        readiness=readiness,
        temp_f_high=temp_f_high,
    )
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
            WHERE status = 'done'
              AND date(log_date) BETWEEN date(?, ? || ' day') AND date(?)
        )
        {recommendation_sql}
        ORDER BY random()
        LIMIT ?
        """,
        (target_date, f"-{lookback_window_days}", target_date, suggestion_count),
    ).fetchall()

    activity_suggestions = _hydrate_activities(conn, activities)
    conn.close()

    return {
        "date": target_date,
        "rain_chance": effective_rain_chance,
        "readiness": readiness,
        "weather": weather,
        "appointments": [dict(row) for row in appointments],
        "active_timed_events": [dict(row) for row in timed_events],
        "annual_reminders": annual_reminders,
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
def add_appointment(
    title: str,
    appt_dt: str,
    appt_end_dt: str = "",
    location: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Add an appointment with ISO datetimes like 2026-06-17T09:00."""

    trimmed_title = title.strip()
    if not trimmed_title:
        return {"ok": False, "error": "title cannot be empty"}

    normalized_end = appt_end_dt.strip() or None
    datetime_error = _validate_appointment_datetimes(appt_dt, normalized_end)
    if datetime_error:
        return {"ok": False, "error": datetime_error}

    conn = _connect()
    cursor = conn.execute(
        """
        INSERT INTO appointments (title, location, appt_dt, appt_end_dt, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (trimmed_title, location.strip() or None, appt_dt, normalized_end, notes.strip() or None),
    )
    appointment_id = cursor.lastrowid
    if appointment_id is None:
        conn.close()
        return {"ok": False, "error": "Failed to create appointment"}

    conn.commit()
    appointment = _get_appointment(conn, appointment_id)
    conn.close()

    return {"ok": True, "id": appointment_id, "appointment": appointment}


@mcp.tool()
def list_appointments(start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    """List appointments on or after start_date, optionally through end_date, ordered by time."""

    start = _as_date(start_date)
    try:
        _parse_iso_date(start)
    except ValueError:
        return {"ok": False, "error": "start_date must be YYYY-MM-DD"}

    if end_date is not None:
        try:
            _parse_iso_date(end_date)
        except ValueError:
            return {"ok": False, "error": "end_date must be YYYY-MM-DD"}
        if end_date < start:
            return {"ok": False, "error": "end_date must be on or after start_date"}

    conn = _connect()
    if end_date is None:
        rows = conn.execute(
            """
            SELECT id, title, location, appt_dt, appt_end_dt, notes
            FROM appointments
            WHERE date(appt_dt) = date(?)
            ORDER BY appt_dt ASC
            """,
            (start,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, title, location, appt_dt, appt_end_dt, notes
            FROM appointments
            WHERE date(appt_dt) BETWEEN date(?) AND date(?)
            ORDER BY appt_dt ASC
            """,
            (start, end_date),
        ).fetchall()
    conn.close()

    return {
        "ok": True,
        "start_date": start,
        "end_date": end_date or start,
        "appointments": [dict(row) for row in rows],
    }


@mcp.tool()
def update_appointment(
    appointment_id: int,
    title: str | None = None,
    appt_dt: str | None = None,
    appt_end_dt: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update an appointment. Empty end time, location, or notes clear those fields."""

    conn = _connect()
    existing = _get_appointment(conn, appointment_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Appointment {appointment_id} not found"}

    updates: dict[str, Any] = {}
    if title is not None:
        trimmed_title = title.strip()
        if not trimmed_title:
            conn.close()
            return {"ok": False, "error": "title cannot be empty"}
        updates["title"] = trimmed_title

    effective_appt_dt = appt_dt if appt_dt is not None else str(existing["appt_dt"])
    effective_appt_end_dt = existing["appt_end_dt"]

    if appt_dt is not None:
        updates["appt_dt"] = appt_dt

    if appt_end_dt is not None:
        effective_appt_end_dt = appt_end_dt.strip() or None
        updates["appt_end_dt"] = effective_appt_end_dt

    datetime_error = _validate_appointment_datetimes(effective_appt_dt, effective_appt_end_dt)
    if datetime_error:
        conn.close()
        return {"ok": False, "error": datetime_error}

    if location is not None:
        updates["location"] = location.strip() or None

    if notes is not None:
        updates["notes"] = notes.strip() or None

    if not updates:
        conn.close()
        return {"ok": False, "error": "No fields provided to update"}

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(
        f"UPDATE appointments SET {assignments} WHERE id = ?",
        (*updates.values(), appointment_id),
    )
    conn.commit()
    appointment = _get_appointment(conn, appointment_id)
    conn.close()

    return {"ok": True, "appointment": appointment}


@mcp.tool()
def delete_appointment(appointment_id: int) -> dict[str, Any]:
    """Delete an appointment by id."""

    conn = _connect()
    existing = _get_appointment(conn, appointment_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Appointment {appointment_id} not found"}

    conn.execute("DELETE FROM appointments WHERE id = ?", (appointment_id,))
    conn.commit()
    conn.close()

    return {"ok": True, "deleted_appointment": existing}


@mcp.tool()
def add_timed_event(
    title: str,
    start_date: str,
    end_date: str,
    description: str = "",
    url: str = "",
) -> dict[str, Any]:
    """Add a timed event with date range in YYYY-MM-DD format."""

    trimmed_title = title.strip()
    if not trimmed_title:
        return {"ok": False, "error": "title cannot be empty"}

    date_error = _validate_date_range(start_date, end_date)
    if date_error:
        return {"ok": False, "error": date_error}

    conn = _connect()
    cursor = conn.execute(
        """
        INSERT INTO timed_events (title, description, url, start_date, end_date)
        VALUES (?, ?, ?, ?, ?)
        """,
        (trimmed_title, description.strip() or None, url.strip() or None, start_date, end_date),
    )
    timed_event_id = cursor.lastrowid
    if timed_event_id is None:
        conn.close()
        return {"ok": False, "error": "Failed to create timed event"}

    conn.commit()
    timed_event = _get_timed_event(conn, timed_event_id)
    conn.close()

    return {"ok": True, "id": timed_event_id, "timed_event": timed_event}


@mcp.tool()
def list_timed_events(
    start_date: str | None = None,
    end_date: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """List timed events, optionally filtered to events overlapping a date window and/or by status."""

    window_start = start_date
    window_end = end_date
    if window_start is None and window_end is not None:
        window_start = window_end
    if window_end is None and window_start is not None:
        window_end = window_start

    if window_start is not None and window_end is not None:
        date_error = _validate_date_range(window_start, window_end)
        if date_error:
            return {"ok": False, "error": date_error}

    normalized_status = None
    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in {"active", "inactive"}:
            return {"ok": False, "error": "status must be active or inactive"}

    conn = _connect()
    sql = """
        SELECT id, title, description, url, start_date, end_date, status
        FROM timed_events
        WHERE 1 = 1
    """
    params: list[Any] = []

    if window_start is not None and window_end is not None:
        sql += """
          AND date(end_date) >= date(?)
          AND date(start_date) <= date(?)
        """
        params.extend([window_start, window_end])

    if normalized_status is not None:
        sql += "\n          AND status = ?"
        params.append(normalized_status)

    sql += "\n        ORDER BY start_date ASC, end_date ASC, title COLLATE NOCASE ASC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return {
        "ok": True,
        "start_date": window_start,
        "end_date": window_end,
        "status": normalized_status,
        "timed_events": [dict(row) for row in rows],
    }


@mcp.tool()
def update_timed_event(
    timed_event_id: int,
    title: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    description: str | None = None,
    url: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update a timed event. Empty description or url clears those fields."""

    conn = _connect()
    existing = _get_timed_event(conn, timed_event_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Timed event {timed_event_id} not found"}

    updates: dict[str, Any] = {}
    if title is not None:
        trimmed_title = title.strip()
        if not trimmed_title:
            conn.close()
            return {"ok": False, "error": "title cannot be empty"}
        updates["title"] = trimmed_title

    effective_start_date = start_date if start_date is not None else str(existing["start_date"])
    effective_end_date = end_date if end_date is not None else str(existing["end_date"])
    date_error = _validate_date_range(effective_start_date, effective_end_date)
    if date_error:
        conn.close()
        return {"ok": False, "error": date_error}

    if start_date is not None:
        updates["start_date"] = start_date
    if end_date is not None:
        updates["end_date"] = end_date
    if description is not None:
        updates["description"] = description.strip() or None
    if url is not None:
        updates["url"] = url.strip() or None

    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in {"active", "inactive"}:
            conn.close()
            return {"ok": False, "error": "status must be active or inactive"}
        updates["status"] = normalized_status

    if not updates:
        conn.close()
        return {"ok": False, "error": "No fields provided to update"}

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(
        f"UPDATE timed_events SET {assignments} WHERE id = ?",
        (*updates.values(), timed_event_id),
    )
    conn.commit()
    timed_event = _get_timed_event(conn, timed_event_id)
    conn.close()

    return {"ok": True, "timed_event": timed_event}


@mcp.tool()
def delete_timed_event(timed_event_id: int) -> dict[str, Any]:
    """Delete a timed event by id."""

    conn = _connect()
    existing = _get_timed_event(conn, timed_event_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Timed event {timed_event_id} not found"}

    conn.execute("DELETE FROM timed_events WHERE id = ?", (timed_event_id,))
    conn.commit()
    conn.close()

    return {"ok": True, "deleted_timed_event": existing}


@mcp.tool()
def add_annual_event(
    title: str,
    event_date: str,
    description: str = "",
    reminder_days_before: int = 7,
) -> dict[str, Any]:
    """Add an annual recurring event with date YYYY-MM-DD and optional reminder lead time."""

    trimmed_title = title.strip()
    if not trimmed_title:
        return {"ok": False, "error": "title cannot be empty"}

    if reminder_days_before < 0:
        return {"ok": False, "error": "reminder_days_before cannot be negative"}

    try:
        _parse_iso_date(event_date)
    except ValueError:
        return {"ok": False, "error": "event_date must be YYYY-MM-DD"}

    conn = _connect()
    cursor = conn.execute(
        """
        INSERT INTO annual_events (title, event_date, description, reminder_days_before)
        VALUES (?, ?, ?, ?)
        """,
        (trimmed_title, event_date, description.strip() or None, reminder_days_before),
    )
    annual_event_id = cursor.lastrowid
    if annual_event_id is None:
        conn.close()
        return {"ok": False, "error": "Failed to create annual event"}

    conn.commit()
    annual_event = _get_annual_event(conn, annual_event_id)
    conn.close()

    return {"ok": True, "id": annual_event_id, "annual_event": annual_event}


@mcp.tool()
def list_annual_events(status: str | None = None) -> dict[str, Any]:
    """List annual events, optionally filtered by active or inactive status."""

    normalized_status = None
    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in {"active", "inactive"}:
            return {"ok": False, "error": "status must be active or inactive"}

    conn = _connect()
    if normalized_status is None:
        rows = conn.execute(
            """
            SELECT id, title, event_date, description, reminder_days_before, status
            FROM annual_events
            ORDER BY event_date ASC, title COLLATE NOCASE ASC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, title, event_date, description, reminder_days_before, status
            FROM annual_events
            WHERE status = ?
            ORDER BY event_date ASC, title COLLATE NOCASE ASC
            """,
            (normalized_status,),
        ).fetchall()
    conn.close()

    return {"ok": True, "status": normalized_status, "annual_events": [dict(row) for row in rows]}


@mcp.tool()
def update_annual_event(
    annual_event_id: int,
    title: str | None = None,
    event_date: str | None = None,
    description: str | None = None,
    reminder_days_before: int | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update an annual event. Empty description clears text; status can be active or inactive."""

    conn = _connect()
    existing = _get_annual_event(conn, annual_event_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Annual event {annual_event_id} not found"}

    updates: dict[str, Any] = {}
    if title is not None:
        trimmed_title = title.strip()
        if not trimmed_title:
            conn.close()
            return {"ok": False, "error": "title cannot be empty"}
        updates["title"] = trimmed_title

    if event_date is not None:
        try:
            _parse_iso_date(event_date)
        except ValueError:
            conn.close()
            return {"ok": False, "error": "event_date must be YYYY-MM-DD"}
        updates["event_date"] = event_date

    if description is not None:
        updates["description"] = description.strip() or None

    if reminder_days_before is not None:
        if reminder_days_before < 0:
            conn.close()
            return {"ok": False, "error": "reminder_days_before cannot be negative"}
        updates["reminder_days_before"] = reminder_days_before

    if status is not None:
        normalized_status = status.strip().lower()
        if normalized_status not in {"active", "inactive"}:
            conn.close()
            return {"ok": False, "error": "status must be active or inactive"}
        updates["status"] = normalized_status

    if not updates:
        conn.close()
        return {"ok": False, "error": "No fields provided to update"}

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(
        f"UPDATE annual_events SET {assignments} WHERE id = ?",
        (*updates.values(), annual_event_id),
    )
    conn.commit()

    updated = _get_annual_event(conn, annual_event_id)
    conn.close()

    return {"ok": True, "annual_event": updated}


@mcp.tool()
def delete_annual_event(annual_event_id: int) -> dict[str, Any]:
    """Delete an annual event by id."""

    conn = _connect()
    existing = _get_annual_event(conn, annual_event_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Annual event {annual_event_id} not found"}

    conn.execute("DELETE FROM annual_events WHERE id = ?", (annual_event_id,))
    conn.commit()
    conn.close()

    return {"ok": True, "deleted_annual_event": existing}


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
def delete_activity(activity_id: int) -> dict[str, Any]:
    """Delete an activity by id."""

    conn = _connect()
    existing = _get_activity(conn, activity_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Activity {activity_id} not found"}

    conn.execute("DELETE FROM activity_log WHERE activity_id = ?", (activity_id,))
    conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))
    conn.commit()
    conn.close()

    return {"ok": True, "deleted_activity": existing}


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
