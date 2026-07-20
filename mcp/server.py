from __future__ import annotations

import json
import logging
import random
import ssl
import sqlite3
import calendar
from datetime import date as date_type
from datetime import datetime as datetime_type
from datetime import timedelta
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


_WEEKDAY_NAME_TO_INDEX = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_WEEKDAY_INDEX_TO_NAME = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]

_ACTIVITY_TYPES = {"eatery", "landmark", "hiking", "geocache", "errand", "cozy_task", "scout"}
_ACTIVITY_STATUSES = {"active", "retired"}


def _available_days_to_mask(available_days: str | list[str] | None) -> tuple[int | None, str | None]:
    if available_days is None:
        return None, None

    tokens: list[str] = []
    if isinstance(available_days, str):
        raw_value = available_days.strip()
        if not raw_value:
            return None, None

        if raw_value.startswith("[") and raw_value.endswith("]"):
            raw_value = raw_value[1:-1]

        if not raw_value.strip():
            return None, None

        tokens = [token.strip().strip("\"'") for token in raw_value.split(",")]
    elif isinstance(available_days, list):
        tokens = [str(token).strip() for token in available_days]
    else:
        return None, "available_days must be a weekday name or a list like [saturday,sunday]"

    weekday_indices: set[int] = set()
    for token in tokens:
        if not token:
            continue
        weekday_index = _WEEKDAY_NAME_TO_INDEX.get(token.lower())
        if weekday_index is None:
            return None, f"Unrecognized weekday '{token}'"
        weekday_indices.add(weekday_index)

    if not weekday_indices:
        return None, None

    mask = 0
    for weekday_index in weekday_indices:
        mask |= 1 << weekday_index

    return mask, None


def _mask_to_available_days(mask: int | None) -> list[str]:
    if mask is None:
        return []

    days: list[str] = []
    for weekday_index, day_name in enumerate(_WEEKDAY_INDEX_TO_NAME):
        if mask & (1 << weekday_index):
            days.append(day_name)
    return days


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


def _planner_settings(settings: dict[str, Any] | None = None) -> dict[str, int]:
    loaded = settings if settings is not None else _load_settings()
    planner_raw = loaded.get("planner") if isinstance(loaded, dict) else None
    planner = planner_raw if isinstance(planner_raw, dict) else {}

    split_hour = _normalize_positive_int(planner.get("appointment_split_hour", 12), 12)
    if split_hour > 23:
        split_hour = 23

    default_duration_minutes = _normalize_positive_int(planner.get("default_appointment_duration_minutes", 60), 60)
    min_travel_buffer_minutes = _normalize_positive_int(planner.get("min_travel_buffer_minutes", 45), 45)

    return {
        "appointment_split_hour": split_hour,
        "default_appointment_duration_minutes": default_duration_minutes,
        "min_travel_buffer_minutes": min_travel_buffer_minutes,
    }


def _normalized_planning_disposition(value: str | None) -> tuple[str | None, str | None]:
    normalized = (value or "optional").strip().lower()
    if normalized not in {"optional", "mandatory"}:
        return None, "planning_disposition must be optional or mandatory"
    return normalized, None


def _effective_appointment_end(appt_dt: str, appt_end_dt: str | None, default_duration_minutes: int) -> str:
    if isinstance(appt_end_dt, str) and appt_end_dt.strip():
        return appt_end_dt.strip()

    start = _parse_iso_datetime(appt_dt)
    derived_end = start + timedelta(minutes=default_duration_minutes)
    return derived_end.isoformat(timespec="minutes")


def _appointment_duration_class(appt_dt: str, appt_end_dt: str, split_hour: int) -> str:
    start = _parse_iso_datetime(appt_dt)
    end = _parse_iso_datetime(appt_end_dt)
    boundary = start.replace(hour=split_hour, minute=0, second=0, microsecond=0)

    if start < boundary and end <= boundary:
        return "morning_only"
    if start >= boundary and end > boundary:
        return "afternoon_only"
    return "all_day"


def _appointment_payload(row: sqlite3.Row | dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = dict(row)
    planner = _planner_settings(settings)
    default_duration = planner["default_appointment_duration_minutes"]
    split_hour = planner["appointment_split_hour"]

    effective_end = _effective_appointment_end(str(payload["appt_dt"]), payload.get("appt_end_dt"), default_duration)
    payload["appt_end_dt"] = effective_end
    payload["planning_disposition"] = str(payload.get("planning_disposition") or "optional").strip().lower()
    payload["duration_class"] = _appointment_duration_class(str(payload["appt_dt"]), effective_end, split_hour)
    return payload


def _validate_mandatory_appointment_constraints(
    conn: sqlite3.Connection,
    appt_dt: str,
    appt_end_dt: str,
    min_travel_buffer_minutes: int,
    exclude_appointment_id: int | None = None,
) -> str | None:
    appt_date = _parse_iso_datetime(appt_dt).date().isoformat()
    rows = conn.execute(
        """
        SELECT id, appt_dt, appt_end_dt
        FROM appointments
        WHERE planning_disposition = 'mandatory'
          AND date(appt_dt) = date(?)
        ORDER BY appt_dt ASC
        """,
        (appt_date,),
    ).fetchall()

    windows: list[tuple[int, datetime_type, datetime_type]] = []
    for row in rows:
        existing_id = int(row["id"])
        if exclude_appointment_id is not None and existing_id == exclude_appointment_id:
            continue
        start = _parse_iso_datetime(row["appt_dt"])
        end = _parse_iso_datetime(row["appt_end_dt"])
        windows.append((existing_id, start, end))

    candidate_start = _parse_iso_datetime(appt_dt)
    candidate_end = _parse_iso_datetime(appt_end_dt)

    for _existing_id, existing_start, existing_end in windows:
        if candidate_start < existing_end and existing_start < candidate_end:
            return "mandatory appointments must not overlap"

    combined: list[tuple[int, datetime_type, datetime_type]] = [(-1, candidate_start, candidate_end), *windows]
    combined.sort(key=lambda window: window[1])

    for previous, current in zip(combined, combined[1:]):
        previous_end = previous[2]
        current_start = current[1]
        gap_minutes = (current_start - previous_end).total_seconds() / 60.0
        if gap_minutes < min_travel_buffer_minutes:
            return f"mandatory appointments require at least {min_travel_buffer_minutes} minutes between appointments"

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


def _activities_activity_type_constraint_allows_hiking(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'activities'"
    ).fetchone()
    if row is None:
        return True

    create_sql = str(row["sql"] or "").lower()
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


def _migrate_schema(conn: sqlite3.Connection) -> None:
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
        activity["available_days"] = _mask_to_available_days(activity.get("day_of_week_mask"))
        if activity.get("activity_type") is None:
            activity["activity_type"] = _activity_planner_type(activity)
        if activity.get("city") is None:
            activity["city"] = _activity_city(activity)
        if activity.get("location_detail") is None:
            activity["location_detail"] = activity.get("location")
        if activity.get("is_evergreen") is None:
            activity["is_evergreen"] = 1
        if activity.get("status") is None:
            activity["status"] = "active"
    return activities


def _unique_category_activity_rows(rows: list[sqlite3.Row], limit: int) -> list[sqlite3.Row]:
    if limit <= 0:
        return []

    selected: list[sqlite3.Row] = []
    seen_categories: set[str] = set()
    for row in rows:
        category_raw = row["category"]
        if isinstance(category_raw, str):
            category_key = category_raw.strip().lower() or "__uncategorized__"
        else:
            category_key = "__uncategorized__"

        if category_key in seen_categories:
            continue

        seen_categories.add(category_key)
        selected.append(row)
        if len(selected) >= limit:
            break

    return selected


def _category_key(category: str | None) -> str:
    if isinstance(category, str) and category.strip():
        return category.strip().lower()
    return "__uncategorized__"


def _city_token(location: Any) -> str | None:
    if not isinstance(location, str):
        return None
    normalized = location.strip().lower()
    if not normalized:
        return None
    return normalized.split(",", 1)[0].strip() or None


def _normalize_non_negative(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0:
        return default
    return parsed


def _normalize_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 1:
        return default
    return parsed


def _ranking_settings(settings: dict[str, Any]) -> dict[str, Any]:
    ranking_raw = settings.get("ranking")
    ranking = ranking_raw if isinstance(ranking_raw, dict) else {}

    enabled = bool(ranking.get("enabled", False))
    novelty_weight = _normalize_non_negative(ranking.get("novelty_weight", 0.6), 0.6)
    city_weight = _normalize_non_negative(ranking.get("city_recency_weight", 0.3), 0.3)
    activity_weight = _normalize_non_negative(ranking.get("activity_recency_weight", 0.1), 0.1)
    city_window_days = _normalize_positive_int(ranking.get("city_recency_window_days", 30), 30)

    random_seed: int | None = None
    random_seed_raw = ranking.get("random_seed")
    if random_seed_raw is not None:
        try:
            random_seed = int(random_seed_raw)
        except (TypeError, ValueError):
            random_seed = None

    return {
        "enabled": enabled,
        "novelty_weight": novelty_weight,
        "city_weight": city_weight,
        "activity_weight": activity_weight,
        "city_window_days": city_window_days,
        "random_seed": random_seed,
    }


def _days_since(target: date_type, log_date_value: str) -> int | None:
    try:
        log_date = _parse_iso_date(log_date_value)
    except ValueError:
        return None
    return (target - log_date).days


def _scale_days(days: int | None, window_days: int) -> float:
    if days is None:
        return 0.5
    if days <= 0:
        return 0.0
    return min(days, window_days) / float(window_days)


def _weighted_random_unique_category_rows(
    rows: list[sqlite3.Row],
    scores_by_id: dict[int, float],
    limit: int,
    rng: random.Random,
) -> list[sqlite3.Row]:
    if limit <= 0:
        return []

    remaining = list(rows)
    selected: list[sqlite3.Row] = []
    seen_categories: set[str] = set()

    while remaining and len(selected) < limit:
        candidates = [row for row in remaining if _category_key(row["category"]) not in seen_categories]
        if not candidates:
            break

        weights = [max(0.0, float(scores_by_id.get(int(row["id"]), 0.0))) for row in candidates]
        if sum(weights) <= 0:
            pick = rng.choice(candidates)
        else:
            pick = rng.choices(candidates, weights=weights, k=1)[0]

        selected.append(pick)
        pick_id = int(pick["id"])
        seen_categories.add(_category_key(pick["category"]))
        remaining = [row for row in remaining if int(row["id"]) != pick_id]

    return selected


def _ranked_activity_rows(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    target_date: str,
    ranking: dict[str, Any],
    limit: int,
) -> list[sqlite3.Row]:
    if limit <= 0 or not rows:
        return []

    target = _parse_iso_date(target_date)
    window_days = int(ranking["city_window_days"])
    novelty_weight = float(ranking["novelty_weight"])
    city_weight = float(ranking["city_weight"])
    activity_weight = float(ranking["activity_weight"])

    candidate_ids = [int(row["id"]) for row in rows]

    any_logs_rows = conn.execute(
        f"SELECT DISTINCT activity_id FROM activity_log WHERE activity_id IN ({', '.join('?' for _ in candidate_ids)})",
        candidate_ids,
    ).fetchall()
    logged_activity_ids = {int(row["activity_id"]) for row in any_logs_rows}

    activity_done_rows = conn.execute(
        f"""
        SELECT activity_id, MAX(log_date) AS last_done
        FROM activity_log
        WHERE status = 'done' AND activity_id IN ({', '.join('?' for _ in candidate_ids)})
        GROUP BY activity_id
        """,
        candidate_ids,
    ).fetchall()
    last_done_by_activity: dict[int, str] = {
        int(row["activity_id"]): row["last_done"]
        for row in activity_done_rows
        if isinstance(row["last_done"], str) and row["last_done"].strip()
    }

    city_done_rows = conn.execute(
        """
        SELECT a.location AS location, l.log_date AS log_date
        FROM activity_log l
        JOIN activities a ON a.id = l.activity_id
        WHERE l.status = 'done'
        ORDER BY l.log_date DESC, l.id DESC
        """
    ).fetchall()
    last_done_by_city: dict[str, str] = {}
    for row in city_done_rows:
        city = _city_token(row["location"])
        if city is None or city in last_done_by_city:
            continue
        log_date_value = row["log_date"]
        if isinstance(log_date_value, str) and log_date_value.strip():
            last_done_by_city[city] = log_date_value

    scores_by_id: dict[int, float] = {}
    for row in rows:
        activity_id = int(row["id"])

        novelty_score = 1.0 if activity_id not in logged_activity_ids else 0.0

        city = _city_token(row["location"])
        city_days = _days_since(target, last_done_by_city[city]) if city is not None and city in last_done_by_city else None
        city_score = _scale_days(city_days, window_days)

        activity_days = _days_since(target, last_done_by_activity[activity_id]) if activity_id in last_done_by_activity else None
        activity_score = _scale_days(activity_days, window_days)

        score = (novelty_weight * novelty_score) + (city_weight * city_score) + (activity_weight * activity_score)
        scores_by_id[activity_id] = max(0.0, score)

    rng = random.Random(ranking["random_seed"]) if ranking["random_seed"] is not None else random.Random()
    return _weighted_random_unique_category_rows(rows, scores_by_id, limit, rng)


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
        SELECT id, title, description, location, category, activity_type, city, location_detail, is_evergreen, status, weather_sensitive, physical_intensity, repeatability_factor, day_of_week_mask
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
        SELECT id, title, location, appt_dt, appt_end_dt, planning_disposition, notes
        FROM appointments
        WHERE id = ?
        """,
        (appointment_id,),
    ).fetchone()
    if row is None:
        return None

    return _appointment_payload(row)


def _get_template(conn: sqlite3.Connection, template_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, name, description, status, created_at
        FROM templates
        WHERE id = ?
        """,
        (template_id,),
    ).fetchone()
    if row is None:
        return None

    template = dict(row)
    template["slots"] = _template_slots_for_template(conn, template["id"])
    return template


def _template_slots_for_template(conn: sqlite3.Connection, template_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, template_id, slot_order, slot_type, required, location_scope, fallback_slot_type, created_at
        FROM template_slots
        WHERE template_id = ?
        ORDER BY slot_order ASC, id ASC
        """,
        (template_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _get_anchor(conn: sqlite3.Connection, anchor_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, name, city, location_detail, duration, template_id, status, created_at
        FROM anchors
        WHERE id = ?
        """,
        (anchor_id,),
    ).fetchone()
    if row is None:
        return None

    anchor = dict(row)
    template = _get_template(conn, anchor["template_id"])
    anchor["template"] = template
    return anchor


def _get_template_slot(conn: sqlite3.Connection, slot_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, template_id, slot_order, slot_type, required, location_scope, fallback_slot_type, created_at
        FROM template_slots
        WHERE id = ?
        """,
        (slot_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def _get_daily_plan(conn: sqlite3.Connection, plan_date: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, plan_date, plan_state, anchor_source, anchor_ref_id, created_at, updated_at
        FROM daily_plans
        WHERE plan_date = ?
        """,
        (plan_date,),
    ).fetchone()
    if row is None:
        return None

    plan = dict(row)
    items = conn.execute(
        """
        SELECT id, daily_plan_id, slot_type, activity_id, status, completion_notes, was_fallback, source_type, source_ref_id, created_at
        FROM daily_plan_items
        WHERE daily_plan_id = ?
        ORDER BY id ASC
        """,
        (plan["id"],),
    ).fetchall()
    plan["items"] = [_daily_plan_item_payload(conn, item) for item in items]

    if plan["anchor_source"] == "user_anchor" and plan["anchor_ref_id"] is not None:
        plan["anchor"] = _get_anchor(conn, int(plan["anchor_ref_id"]))
    elif plan["anchor_source"] in {"mandatory_appointment", "multi_mandatory_appointments"}:
        plan["appointments"] = _mandatory_appointments_for_date(conn, plan_date)

    return plan


def _mandatory_appointments_for_date(conn: sqlite3.Connection, plan_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, location, appt_dt, appt_end_dt, planning_disposition, notes
        FROM appointments
        WHERE planning_disposition = 'mandatory'
          AND date(appt_dt) = date(?)
        ORDER BY appt_dt ASC, id ASC
        """,
        (plan_date,),
    ).fetchall()
    return [_appointment_payload(row) for row in rows]


def _active_anchor_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT a.id, a.name, a.city, a.location_detail, a.duration, a.template_id, a.status, a.created_at, t.name AS template_name
        FROM anchors a
        JOIN templates t ON t.id = a.template_id
        WHERE a.status = 'active' AND t.status = 'active'
        ORDER BY a.name COLLATE NOCASE ASC, a.id ASC
        """
    ).fetchall()


def _anchor_option_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    anchor = dict(row)
    anchor["template"] = _get_template(conn, anchor["template_id"])
    return anchor


def _replace_daily_plan(conn: sqlite3.Connection, plan_date: str) -> None:
    existing = conn.execute("SELECT id FROM daily_plans WHERE plan_date = ?", (plan_date,)).fetchone()
    if existing is None:
        return
    conn.execute("DELETE FROM daily_plans WHERE id = ?", (existing["id"],))


def _daily_plan_item_payload(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    if item.get("activity_id") is not None:
        item["activity"] = _get_activity(conn, int(item["activity_id"]))
    return item


def _activity_city(activity: dict[str, Any]) -> str | None:
    city = activity.get("city")
    if isinstance(city, str) and city.strip():
        return city.strip().lower()
    return _city_token(activity.get("location"))


def _activity_text(activity: dict[str, Any]) -> str:
    parts = [activity.get("title"), activity.get("description"), activity.get("category"), activity.get("location")]
    return " ".join(str(part) for part in parts if isinstance(part, str) and part.strip()).lower()


def _activity_planner_type(activity: dict[str, Any]) -> str | None:
    activity_type = activity.get("activity_type")
    if isinstance(activity_type, str) and activity_type.strip():
        normalized = activity_type.strip().lower()
        if normalized in {"eatery", "landmark", "hiking", "geocache", "errand", "cozy_task", "scout"}:
            return normalized

    category = str(activity.get("category") or "").strip().lower()
    text = _activity_text(activity)

    category_aliases = {
        "eatery": {"eatery", "coffee", "cafe", "restaurant", "bakery", "diner", "food", "lunch", "breakfast"},
        "landmark": {"landmark", "museum", "park", "viewpoint", "historic", "neighborhood"},
        "hiking": {"hiking", "nature trail", "trail", "hike"},
        "geocache": {"geocache", "cache"},
        "errand": {"errand", "shopping", "store", "retail", "pharmacy", "grocery", "hardware", "pickup"},
        "cozy_task": {"cozy", "home", "indoor", "reading", "movie", "craft", "relax", "chores"},
        "scout": {"scout", "explore", "discovery", "new", "adventure"},
    }

    for planner_type, aliases in category_aliases.items():
        if category in aliases:
            return planner_type
        if any(alias in text for alias in aliases):
            return planner_type

    return None


def _activity_matches_location_scope(activity: dict[str, Any], anchor_city: str, location_scope: str) -> bool:
    if location_scope == "anywhere":
        return True

    activity_city = _activity_city(activity)
    if location_scope == "anchor_city":
        return activity_city == anchor_city

    if location_scope == "exact_location":
        location = activity.get("location_detail") or activity.get("location")
        if isinstance(location, str) and location.strip():
            return location.strip().lower() == anchor_city or anchor_city in location.strip().lower()
        return False

    return False


def _activity_matches_slot(activity: dict[str, Any], slot_type: str, anchor_city: str, location_scope: str) -> bool:
    if str(activity.get("status") or "active").strip().lower() != "active":
        return False

    activity_type = activity.get("activity_type")
    if not isinstance(activity_type, str) or not activity_type.strip():
        return False

    normalized_type = activity_type.strip().lower()
    if normalized_type != slot_type:
        return False

    return _activity_matches_location_scope(activity, anchor_city, location_scope)


def _eligible_activities_for_slot(conn: sqlite3.Connection, slot: dict[str, Any], anchor_city: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, title, description, location, category, activity_type, city, location_detail, is_evergreen, status, weather_sensitive, physical_intensity, repeatability_factor, day_of_week_mask
        FROM activities
        WHERE status = 'active'
        ORDER BY id ASC
        """
    ).fetchall()

    candidates: list[dict[str, Any]] = []
    for row in rows:
        activity = dict(row)
        if activity.get("location_detail") is None:
            activity["location_detail"] = activity.get("location")
        if _activity_matches_slot(activity, slot["slot_type"], anchor_city, slot["location_scope"]):
            candidates.append(activity)

    return candidates


def _pick_activity_for_slot(conn: sqlite3.Connection, slot: dict[str, Any], anchor_city: str) -> tuple[dict[str, Any] | None, bool]:
    candidates = _eligible_activities_for_slot(conn, slot, anchor_city)
    if candidates:
        return candidates[0], False

    fallback_type = slot.get("fallback_slot_type")
    if isinstance(fallback_type, str) and fallback_type.strip():
        fallback_slot = dict(slot)
        fallback_slot["slot_type"] = fallback_type.strip().lower()
        fallback_candidates = _eligible_activities_for_slot(conn, fallback_slot, anchor_city)
        if fallback_candidates:
            return fallback_candidates[0], True

    return None, False


def _build_daily_plan_items_for_anchor(conn: sqlite3.Connection, daily_plan_id: int, anchor: dict[str, Any]) -> None:
    template = anchor.get("template") or {}
    slots = template.get("slots") or []
    anchor_city = str(anchor.get("city") or "").strip().lower()

    if not slots:
        conn.execute(
            """
            INSERT INTO daily_plan_items (daily_plan_id, slot_type, activity_id, status, completion_notes, was_fallback, source_type, source_ref_id)
            VALUES (?, 'anchor', NULL, 'planned', NULL, 0, 'anchor', ?)
            """,
            (daily_plan_id, anchor["id"]),
        )
        return

    for slot in slots:
        activity, was_fallback = _pick_activity_for_slot(conn, slot, anchor_city)
        completion_notes = None
        if activity is None:
            if int(slot.get("required") or 0) == 1:
                completion_notes = f"No eligible activity found for required slot {slot['slot_type']}"
            else:
                completion_notes = f"No eligible activity found for optional slot {slot['slot_type']}"

        conn.execute(
            """
            INSERT INTO daily_plan_items (daily_plan_id, slot_type, activity_id, status, completion_notes, was_fallback, source_type, source_ref_id)
            VALUES (?, ?, ?, 'planned', ?, ?, 'template_slot', ?)
            """,
            (daily_plan_id, slot["slot_type"], activity["id"] if activity is not None else None, completion_notes, 1 if was_fallback else 0, slot["id"]),
        )


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
            SELECT id, title, description, location, category, activity_type, city, location_detail, is_evergreen, status, weather_sensitive, physical_intensity, repeatability_factor, day_of_week_mask
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
        SELECT id, title, description, location, category, activity_type, city, location_detail, is_evergreen, status, weather_sensitive, physical_intensity, repeatability_factor, day_of_week_mask
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
        SELECT id, title, description, location, category, activity_type, city, location_detail, is_evergreen, status, weather_sensitive, physical_intensity, repeatability_factor, day_of_week_mask
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
    target_weekday_index: int | None = None,
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

    if target_weekday_index is not None:
        day_bit = 1 << target_weekday_index
        clauses.append(f"(a.day_of_week_mask IS NULL OR (a.day_of_week_mask & {day_bit}) != 0)")

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
        SELECT id, title, location, appt_dt, appt_end_dt, planning_disposition, notes
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
    target_weekday_index = _parse_iso_date(target_date).weekday()

    suggestion_count = int(settings.get("activity_suggestions_per_day", 3))
    lookback_days = int(settings.get("briefing_lookback_days", 7))
    if lookback_days < 1:
        lookback_days = 1
    recommendation_clauses = _activity_recommendation_clauses(
        rain_chance=effective_rain_chance,
        readiness=readiness,
        temp_f_high=temp_f_high,
        target_weekday_index=target_weekday_index,
    )
    recommendation_sql = ""
    if recommendation_clauses:
        recommendation_sql = "\n        AND " + "\n        AND ".join(recommendation_clauses)

    candidate_activities = conn.execute(
        f"""
        SELECT a.id, a.title, a.description, a.location, a.category, a.weather_sensitive, a.physical_intensity, a.repeatability_factor, a.day_of_week_mask
        FROM activities a
        WHERE NOT EXISTS (
            SELECT 1
            FROM activity_log l
            WHERE l.activity_id = a.id
              AND l.status = 'done'
              AND (julianday(date(?)) - julianday(date(l.log_date))) >= 0
              AND (julianday(date(?)) - julianday(date(l.log_date))) < (? * coalesce(a.repeatability_factor, 2))
        )
        {recommendation_sql}
        """,
        (target_date, target_date, lookback_days),
    ).fetchall()

    ranking = _ranking_settings(settings)
    if ranking["enabled"]:
        activities = _ranked_activity_rows(
            conn=conn,
            rows=candidate_activities,
            target_date=target_date,
            ranking=ranking,
            limit=suggestion_count,
        )
    else:
        shuffled_candidates = list(candidate_activities)
        random.shuffle(shuffled_candidates)
        activities = _unique_category_activity_rows(shuffled_candidates, suggestion_count)

    activity_suggestions = _hydrate_activities(conn, activities)
    conn.close()

    return {
        "date": target_date,
        "rain_chance": effective_rain_chance,
        "readiness": readiness,
        "weather": weather,
        "appointments": [_appointment_payload(row, settings=settings) for row in appointments],
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
    planning_disposition: str = "optional",
    location: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Add an appointment with ISO datetimes like 2026-06-17T09:00."""

    trimmed_title = title.strip()
    if not trimmed_title:
        return {"ok": False, "error": "title cannot be empty"}

    settings = _load_settings()
    planner = _planner_settings(settings)

    normalized_disposition, disposition_error = _normalized_planning_disposition(planning_disposition)
    if disposition_error:
        return {"ok": False, "error": disposition_error}

    normalized_end = _effective_appointment_end(
        appt_dt=appt_dt,
        appt_end_dt=appt_end_dt.strip() or None,
        default_duration_minutes=planner["default_appointment_duration_minutes"],
    )
    datetime_error = _validate_appointment_datetimes(appt_dt, normalized_end)
    if datetime_error:
        return {"ok": False, "error": datetime_error}

    conn = _connect()
    if normalized_disposition == "mandatory":
        mandatory_error = _validate_mandatory_appointment_constraints(
            conn=conn,
            appt_dt=appt_dt,
            appt_end_dt=normalized_end,
            min_travel_buffer_minutes=planner["min_travel_buffer_minutes"],
        )
        if mandatory_error:
            conn.close()
            return {"ok": False, "error": mandatory_error}

    cursor = conn.execute(
        """
        INSERT INTO appointments (title, location, appt_dt, appt_end_dt, planning_disposition, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (trimmed_title, location.strip() or None, appt_dt, normalized_end, normalized_disposition, notes.strip() or None),
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

    settings = _load_settings()
    conn = _connect()
    if end_date is None:
        rows = conn.execute(
            """
            SELECT id, title, location, appt_dt, appt_end_dt, planning_disposition, notes
            FROM appointments
            WHERE date(appt_dt) = date(?)
            ORDER BY appt_dt ASC
            """,
            (start,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, title, location, appt_dt, appt_end_dt, planning_disposition, notes
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
        "appointments": [_appointment_payload(row, settings=settings) for row in rows],
    }


@mcp.tool()
def update_appointment(
    appointment_id: int,
    title: str | None = None,
    appt_dt: str | None = None,
    appt_end_dt: str | None = None,
    planning_disposition: str | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Update an appointment. Empty end time, location, or notes clear those fields."""

    conn = _connect()
    existing = _get_appointment(conn, appointment_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Appointment {appointment_id} not found"}

    settings = _load_settings()
    planner = _planner_settings(settings)

    updates: dict[str, Any] = {}
    if title is not None:
        trimmed_title = title.strip()
        if not trimmed_title:
            conn.close()
            return {"ok": False, "error": "title cannot be empty"}
        updates["title"] = trimmed_title

    effective_appt_dt = appt_dt if appt_dt is not None else str(existing["appt_dt"])
    effective_appt_end_dt = str(existing["appt_end_dt"])
    effective_disposition = str(existing.get("planning_disposition") or "optional")

    if appt_dt is not None:
        updates["appt_dt"] = appt_dt

    if appt_end_dt is not None:
        effective_appt_end_dt = appt_end_dt.strip() or None
        updates["appt_end_dt"] = effective_appt_end_dt

    if planning_disposition is not None:
        normalized_disposition, disposition_error = _normalized_planning_disposition(planning_disposition)
        if disposition_error:
            conn.close()
            return {"ok": False, "error": disposition_error}
        effective_disposition = str(normalized_disposition)
        updates["planning_disposition"] = effective_disposition

    effective_appt_end_dt = _effective_appointment_end(
        appt_dt=effective_appt_dt,
        appt_end_dt=effective_appt_end_dt,
        default_duration_minutes=planner["default_appointment_duration_minutes"],
    )
    updates["appt_end_dt"] = effective_appt_end_dt

    datetime_error = _validate_appointment_datetimes(effective_appt_dt, effective_appt_end_dt)
    if datetime_error:
        conn.close()
        return {"ok": False, "error": datetime_error}

    if effective_disposition == "mandatory":
        mandatory_error = _validate_mandatory_appointment_constraints(
            conn=conn,
            appt_dt=effective_appt_dt,
            appt_end_dt=effective_appt_end_dt,
            min_travel_buffer_minutes=planner["min_travel_buffer_minutes"],
            exclude_appointment_id=appointment_id,
        )
        if mandatory_error:
            conn.close()
            return {"ok": False, "error": mandatory_error}

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


def _normalized_enum_value(value: str | None, allowed: set[str], default: str | None = None) -> tuple[str | None, str | None]:
    if value is None:
        return default, None

    normalized = value.strip().lower()
    if normalized not in allowed:
        return None, f"value must be one of: {', '.join(sorted(allowed))}"
    return normalized, None


@mcp.tool()
def add_template(name: str, description: str = "", status: str = "active") -> dict[str, Any]:
    """Add a planner template."""

    trimmed_name = name.strip()
    if not trimmed_name:
        return {"ok": False, "error": "name cannot be empty"}

    normalized_status, status_error = _normalized_enum_value(status, {"active", "inactive"}, default="active")
    if status_error:
        return {"ok": False, "error": status_error}

    conn = _connect()
    cursor = conn.execute(
        """
        INSERT INTO templates (name, description, status)
        VALUES (?, ?, ?)
        """,
        (trimmed_name, description.strip() or None, normalized_status),
    )
    template_id = cursor.lastrowid
    conn.commit()
    template = _get_template(conn, int(template_id)) if template_id is not None else None
    conn.close()

    if template is None:
        return {"ok": False, "error": "Failed to create template"}
    return {"ok": True, "id": template_id, "template": template}


@mcp.tool()
def list_templates(status: str | None = None) -> dict[str, Any]:
    """List planner templates."""

    normalized_status, status_error = _normalized_enum_value(status, {"active", "inactive"})
    if status_error:
        return {"ok": False, "error": status_error}

    conn = _connect()
    if normalized_status is None:
        rows = conn.execute(
            """
            SELECT id, name, description, status, created_at
            FROM templates
            ORDER BY name COLLATE NOCASE ASC, id ASC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, name, description, status, created_at
            FROM templates
            WHERE status = ?
            ORDER BY name COLLATE NOCASE ASC, id ASC
            """,
            (normalized_status,),
        ).fetchall()

    templates = []
    for row in rows:
        template = dict(row)
        template["slots"] = _template_slots_for_template(conn, template["id"])
        templates.append(template)
    conn.close()

    return {"ok": True, "status": normalized_status, "templates": templates}


@mcp.tool()
def update_template(
    template_id: int,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update a planner template."""

    conn = _connect()
    existing = _get_template(conn, template_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Template {template_id} not found"}

    updates: dict[str, Any] = {}
    if name is not None:
        trimmed_name = name.strip()
        if not trimmed_name:
            conn.close()
            return {"ok": False, "error": "name cannot be empty"}
        updates["name"] = trimmed_name

    if description is not None:
        updates["description"] = description.strip() or None

    if status is not None:
        normalized_status, status_error = _normalized_enum_value(status, {"active", "inactive"})
        if status_error:
            conn.close()
            return {"ok": False, "error": status_error}
        updates["status"] = normalized_status

    if not updates:
        conn.close()
        return {"ok": False, "error": "No fields provided to update"}

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(
        f"UPDATE templates SET {assignments} WHERE id = ?",
        (*updates.values(), template_id),
    )
    conn.commit()
    template = _get_template(conn, template_id)
    conn.close()
    return {"ok": True, "template": template}


@mcp.tool()
def delete_template(template_id: int) -> dict[str, Any]:
    """Delete a planner template."""

    conn = _connect()
    existing = _get_template(conn, template_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Template {template_id} not found"}

    in_use = conn.execute("SELECT 1 FROM anchors WHERE template_id = ? LIMIT 1", (template_id,)).fetchone()
    if in_use is not None:
        conn.close()
        return {"ok": False, "error": f"Template {template_id} is in use by anchors"}

    conn.execute("DELETE FROM template_slots WHERE template_id = ?", (template_id,))
    conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted_template": existing}


@mcp.tool()
def add_anchor(
    name: str,
    city: str,
    template_id: int,
    duration: str = "half_day",
    location_detail: str = "",
    status: str = "active",
) -> dict[str, Any]:
    """Add a planner anchor."""

    trimmed_name = name.strip()
    trimmed_city = city.strip()
    if not trimmed_name:
        return {"ok": False, "error": "name cannot be empty"}
    if not trimmed_city:
        return {"ok": False, "error": "city cannot be empty"}

    normalized_duration, duration_error = _normalized_enum_value(duration, {"half_day", "full_day"}, default="half_day")
    if duration_error:
        return {"ok": False, "error": duration_error}

    normalized_status, status_error = _normalized_enum_value(status, {"active", "inactive"}, default="active")
    if status_error:
        return {"ok": False, "error": status_error}

    conn = _connect()
    template = _get_template(conn, template_id)
    if template is None:
        conn.close()
        return {"ok": False, "error": f"Template {template_id} not found"}

    cursor = conn.execute(
        """
        INSERT INTO anchors (name, city, location_detail, duration, template_id, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (trimmed_name, trimmed_city, location_detail.strip() or None, normalized_duration, template_id, normalized_status),
    )
    anchor_id = cursor.lastrowid
    conn.commit()
    anchor = _get_anchor(conn, int(anchor_id)) if anchor_id is not None else None
    conn.close()

    if anchor is None:
        return {"ok": False, "error": "Failed to create anchor"}
    return {"ok": True, "id": anchor_id, "anchor": anchor}


@mcp.tool()
def list_anchors(status: str | None = None) -> dict[str, Any]:
    """List planner anchors."""

    normalized_status, status_error = _normalized_enum_value(status, {"active", "inactive"})
    if status_error:
        return {"ok": False, "error": status_error}

    conn = _connect()
    if normalized_status is None:
        rows = conn.execute(
            """
            SELECT a.id, a.name, a.city, a.location_detail, a.duration, a.template_id, a.status, a.created_at, t.name AS template_name
            FROM anchors a
            JOIN templates t ON t.id = a.template_id
            ORDER BY a.name COLLATE NOCASE ASC, a.id ASC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT a.id, a.name, a.city, a.location_detail, a.duration, a.template_id, a.status, a.created_at, t.name AS template_name
            FROM anchors a
            JOIN templates t ON t.id = a.template_id
            WHERE a.status = ?
            ORDER BY a.name COLLATE NOCASE ASC, a.id ASC
            """,
            (normalized_status,),
        ).fetchall()

    anchors = []
    for row in rows:
        anchor = dict(row)
        anchor["template"] = _get_template(conn, anchor["template_id"])
        anchors.append(anchor)
    conn.close()
    return {"ok": True, "status": normalized_status, "anchors": anchors}


@mcp.tool()
def update_anchor(
    anchor_id: int,
    name: str | None = None,
    city: str | None = None,
    template_id: int | None = None,
    duration: str | None = None,
    location_detail: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    """Update a planner anchor."""

    conn = _connect()
    existing = _get_anchor(conn, anchor_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Anchor {anchor_id} not found"}

    updates: dict[str, Any] = {}
    if name is not None:
        trimmed_name = name.strip()
        if not trimmed_name:
            conn.close()
            return {"ok": False, "error": "name cannot be empty"}
        updates["name"] = trimmed_name

    if city is not None:
        trimmed_city = city.strip()
        if not trimmed_city:
            conn.close()
            return {"ok": False, "error": "city cannot be empty"}
        updates["city"] = trimmed_city

    if template_id is not None:
        if _get_template(conn, template_id) is None:
            conn.close()
            return {"ok": False, "error": f"Template {template_id} not found"}
        updates["template_id"] = template_id

    if duration is not None:
        normalized_duration, duration_error = _normalized_enum_value(duration, {"half_day", "full_day"})
        if duration_error:
            conn.close()
            return {"ok": False, "error": duration_error}
        updates["duration"] = normalized_duration

    if location_detail is not None:
        updates["location_detail"] = location_detail.strip() or None

    if status is not None:
        normalized_status, status_error = _normalized_enum_value(status, {"active", "inactive"})
        if status_error:
            conn.close()
            return {"ok": False, "error": status_error}
        updates["status"] = normalized_status

    if not updates:
        conn.close()
        return {"ok": False, "error": "No fields provided to update"}

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(
        f"UPDATE anchors SET {assignments} WHERE id = ?",
        (*updates.values(), anchor_id),
    )
    conn.commit()
    anchor = _get_anchor(conn, anchor_id)
    conn.close()
    return {"ok": True, "anchor": anchor}


@mcp.tool()
def delete_anchor(anchor_id: int) -> dict[str, Any]:
    """Delete a planner anchor."""

    conn = _connect()
    existing = _get_anchor(conn, anchor_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Anchor {anchor_id} not found"}

    conn.execute("DELETE FROM anchors WHERE id = ?", (anchor_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted_anchor": existing}


@mcp.tool()
def add_template_slot(
    template_id: int,
    slot_order: int,
    slot_type: str,
    required: int = 0,
    location_scope: str = "anchor_city",
    fallback_slot_type: str | None = None,
) -> dict[str, Any]:
    """Add a slot to a planner template."""

    conn = _connect()
    if _get_template(conn, template_id) is None:
        conn.close()
        return {"ok": False, "error": f"Template {template_id} not found"}

    normalized_slot_type, slot_type_error = _normalized_enum_value(slot_type, {"eatery", "landmark", "geocache", "errand", "cozy_task", "scout"})
    if slot_type_error:
        conn.close()
        return {"ok": False, "error": slot_type_error}

    normalized_scope, scope_error = _normalized_enum_value(location_scope, {"anchor_city", "anywhere", "exact_location"}, default="anchor_city")
    if scope_error:
        conn.close()
        return {"ok": False, "error": scope_error}

    normalized_fallback = None
    if fallback_slot_type is not None:
        normalized_fallback, fallback_error = _normalized_enum_value(fallback_slot_type, {"eatery", "landmark", "geocache", "errand", "cozy_task", "scout"})
        if fallback_error:
            conn.close()
            return {"ok": False, "error": fallback_error}

    try:
        cursor = conn.execute(
            """
            INSERT INTO template_slots (template_id, slot_order, slot_type, required, location_scope, fallback_slot_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (template_id, slot_order, normalized_slot_type, 1 if required else 0, normalized_scope, normalized_fallback),
        )
    except sqlite3.IntegrityError as exc:
        conn.close()
        return {"ok": False, "error": str(exc)}

    slot_id = cursor.lastrowid
    conn.commit()
    slot = _get_template_slot(conn, int(slot_id)) if slot_id is not None else None
    conn.close()
    return {"ok": True, "id": slot_id, "template_slot": slot}


@mcp.tool()
def list_template_slots(template_id: int | None = None) -> dict[str, Any]:
    """List template slots."""

    conn = _connect()
    if template_id is None:
        rows = conn.execute(
            """
            SELECT id, template_id, slot_order, slot_type, required, location_scope, fallback_slot_type, created_at
            FROM template_slots
            ORDER BY template_id ASC, slot_order ASC, id ASC
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, template_id, slot_order, slot_type, required, location_scope, fallback_slot_type, created_at
            FROM template_slots
            WHERE template_id = ?
            ORDER BY slot_order ASC, id ASC
            """,
            (template_id,),
        ).fetchall()
    conn.close()
    return {"ok": True, "template_id": template_id, "template_slots": [dict(row) for row in rows]}


@mcp.tool()
def update_template_slot(
    slot_id: int,
    slot_order: int | None = None,
    slot_type: str | None = None,
    required: int | None = None,
    location_scope: str | None = None,
    fallback_slot_type: str | None = None,
) -> dict[str, Any]:
    """Update a template slot."""

    conn = _connect()
    existing = _get_template_slot(conn, slot_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Template slot {slot_id} not found"}

    updates: dict[str, Any] = {}
    if slot_order is not None:
        updates["slot_order"] = slot_order

    if slot_type is not None:
        normalized_slot_type, slot_type_error = _normalized_enum_value(slot_type, {"eatery", "landmark", "geocache", "errand", "cozy_task", "scout"})
        if slot_type_error:
            conn.close()
            return {"ok": False, "error": slot_type_error}
        updates["slot_type"] = normalized_slot_type

    if required is not None:
        updates["required"] = 1 if required else 0

    if location_scope is not None:
        normalized_scope, scope_error = _normalized_enum_value(location_scope, {"anchor_city", "anywhere", "exact_location"})
        if scope_error:
            conn.close()
            return {"ok": False, "error": scope_error}
        updates["location_scope"] = normalized_scope

    if fallback_slot_type is not None:
        normalized_fallback, fallback_error = _normalized_enum_value(fallback_slot_type, {"eatery", "landmark", "geocache", "errand", "cozy_task", "scout"})
        if fallback_error:
            conn.close()
            return {"ok": False, "error": fallback_error}
        updates["fallback_slot_type"] = normalized_fallback

    if not updates:
        conn.close()
        return {"ok": False, "error": "No fields provided to update"}

    assignments = ", ".join(f"{column} = ?" for column in updates)
    try:
        conn.execute(
            f"UPDATE template_slots SET {assignments} WHERE id = ?",
            (*updates.values(), slot_id),
        )
    except sqlite3.IntegrityError as exc:
        conn.close()
        return {"ok": False, "error": str(exc)}

    conn.commit()
    slot = _get_template_slot(conn, slot_id)
    conn.close()
    return {"ok": True, "template_slot": slot}


@mcp.tool()
def delete_template_slot(slot_id: int) -> dict[str, Any]:
    """Delete a template slot."""

    conn = _connect()
    existing = _get_template_slot(conn, slot_id)
    if existing is None:
        conn.close()
        return {"ok": False, "error": f"Template slot {slot_id} not found"}

    conn.execute("DELETE FROM template_slots WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted_template_slot": existing}


@mcp.tool()
def generate_anchor_options(date: str | None = None) -> dict[str, Any]:
    """Return anchor options for a date without persisting a plan."""

    target_date = _as_date(date)
    conn = _connect()
    mandatory_appointments = _mandatory_appointments_for_date(conn, target_date)

    if len(mandatory_appointments) > 1:
        conn.close()
        return {
            "ok": True,
            "date": target_date,
            "selection_mode": "multi_mandatory_appointments",
            "anchor_options": [],
            "mandatory_appointments": mandatory_appointments,
        }

    if len(mandatory_appointments) == 1:
        conn.close()
        return {
            "ok": True,
            "date": target_date,
            "selection_mode": "mandatory_appointment",
            "anchor_options": [],
            "mandatory_appointments": mandatory_appointments,
            "appointment_anchor": mandatory_appointments[0],
        }

    rows = _active_anchor_rows(conn)
    anchor_options = [_anchor_option_payload(conn, row) for row in rows[:3]]
    conn.close()

    return {
        "ok": True,
        "date": target_date,
        "selection_mode": "user_anchor",
        "anchor_options": anchor_options,
        "mandatory_appointments": [],
    }


@mcp.tool()
def commit_daily_plan(date: str | None = None, selected_anchor_id: int | None = None) -> dict[str, Any]:
    """Persist a daily plan for the selected anchor or mandatory appointment context."""

    target_date = _as_date(date)
    conn = _connect()
    mandatory_appointments = _mandatory_appointments_for_date(conn, target_date)

    selection_mode = "user_anchor"
    anchor_ref_id: int | None = selected_anchor_id
    if len(mandatory_appointments) > 1:
        selection_mode = "multi_mandatory_appointments"
        anchor_ref_id = None
    elif len(mandatory_appointments) == 1:
        selection_mode = "mandatory_appointment"
        anchor_ref_id = int(mandatory_appointments[0]["id"])
    else:
        if selected_anchor_id is None:
            conn.close()
            return {"ok": False, "error": "selected_anchor_id is required when no mandatory appointments exist"}
        if _get_anchor(conn, selected_anchor_id) is None:
            conn.close()
            return {"ok": False, "error": f"Anchor {selected_anchor_id} not found"}

    try:
        conn.execute("BEGIN")
        _replace_daily_plan(conn, target_date)
        cursor = conn.execute(
            """
            INSERT INTO daily_plans (plan_date, plan_state, anchor_source, anchor_ref_id)
            VALUES (?, 'active', ?, ?)
            """,
            (target_date, selection_mode, anchor_ref_id),
        )
        daily_plan_id = int(cursor.lastrowid)

        if selection_mode == "user_anchor":
            anchor = _get_anchor(conn, int(selected_anchor_id)) if selected_anchor_id is not None else None
            if anchor is None:
                raise ValueError(f"Anchor {selected_anchor_id} not found")
            _build_daily_plan_items_for_anchor(conn, daily_plan_id, anchor)
        else:
            for appointment in mandatory_appointments:
                conn.execute(
                    """
                    INSERT INTO daily_plan_items (daily_plan_id, slot_type, activity_id, status, completion_notes, was_fallback, source_type, source_ref_id)
                    VALUES (?, 'appointment', NULL, 'planned', NULL, 0, 'appointment', ?)
                    """,
                    (daily_plan_id, int(appointment["id"])),
                )

        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        return {"ok": False, "error": str(exc)}

    plan = _get_daily_plan(conn, target_date)
    conn.close()
    return {"ok": True, "plan": plan}


@mcp.tool()
def get_daily_plan(date: str | None = None) -> dict[str, Any]:
    """Return a persisted daily plan for a date."""

    target_date = _as_date(date)
    conn = _connect()
    plan = _get_daily_plan(conn, target_date)
    conn.close()
    if plan is None:
        return {"ok": False, "error": f"Daily plan for {target_date} not found"}
    return {"ok": True, "plan": plan}


@mcp.tool()
def list_daily_plans(start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    """List persisted daily plans in a date range."""

    window_start = _as_date(start_date) if start_date is not None else None
    window_end = _as_date(end_date) if end_date is not None else None

    if window_start is not None and window_end is not None:
        date_error = _validate_date_range(window_start, window_end)
        if date_error:
            return {"ok": False, "error": date_error}

    conn = _connect()
    sql = """
        SELECT id, plan_date, plan_state, anchor_source, anchor_ref_id, created_at, updated_at
        FROM daily_plans
        WHERE 1 = 1
    """
    params: list[Any] = []
    if window_start is not None:
        sql += "\n          AND date(plan_date) >= date(?)"
        params.append(window_start)
    if window_end is not None:
        sql += "\n          AND date(plan_date) <= date(?)"
        params.append(window_end)

    sql += "\n        ORDER BY plan_date ASC, id ASC"
    rows = conn.execute(sql, params).fetchall()
    plans = []
    for row in rows:
        plan = _get_daily_plan(conn, row["plan_date"])
        if plan is not None:
            plans.append(plan)
    conn.close()
    return {"ok": True, "start_date": window_start, "end_date": window_end, "daily_plans": plans}


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
    activity_type: str | None = None,
    city: str = "",
    location_detail: str = "",
    is_evergreen: int = 1,
    status: str = "active",
    weather_sensitive: int = 0,
    physical_intensity: int = 1,
    repeatability_factor: float = 2,
    available_days: str | list[str] | None = None,
    urls: list[str] | None = None,
) -> dict[str, Any]:
    """Add an activity suggestion to the activity pool."""

    if repeatability_factor <= 0:
        return {"ok": False, "error": "repeatability_factor must be greater than 0"}

    day_of_week_mask, day_parse_error = _available_days_to_mask(available_days)
    if day_parse_error:
        return {"ok": False, "error": day_parse_error}

    normalized_activity_type, activity_type_error = _normalized_enum_value(activity_type, _ACTIVITY_TYPES)
    if activity_type_error:
        return {"ok": False, "error": activity_type_error}

    normalized_status, status_error = _normalized_enum_value(status, _ACTIVITY_STATUSES, default="active")
    if status_error:
        return {"ok": False, "error": status_error}

    if is_evergreen not in {0, 1}:
        return {"ok": False, "error": "is_evergreen must be 0 or 1"}

    conn = _connect()
    cursor = conn.execute(
        """
        INSERT INTO activities (
            title,
            description,
            location,
            category,
            activity_type,
            city,
            location_detail,
            is_evergreen,
            status,
            weather_sensitive,
            physical_intensity,
            repeatability_factor,
            day_of_week_mask
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            description or None,
            location or None,
            category or None,
            normalized_activity_type,
            city.strip() or None,
            location_detail.strip() or None,
            is_evergreen,
            normalized_status,
            weather_sensitive,
            physical_intensity,
            float(repeatability_factor),
            day_of_week_mask,
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
    activity_type: str | None = None,
    city: str | None = None,
    location_detail: str | None = None,
    is_evergreen: int | None = None,
    status: str | None = None,
    weather_sensitive: int | None = None,
    physical_intensity: int | None = None,
    repeatability_factor: float | None = None,
    available_days: str | list[str] | None = None,
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
    if activity_type is not None:
        normalized_activity_type, activity_type_error = _normalized_enum_value(activity_type, _ACTIVITY_TYPES)
        if activity_type_error:
            conn.close()
            return {"ok": False, "error": activity_type_error}
        updates["activity_type"] = normalized_activity_type
    if city is not None:
        updates["city"] = city.strip() or None
    if location_detail is not None:
        updates["location_detail"] = location_detail.strip() or None
    if is_evergreen is not None:
        if is_evergreen not in {0, 1}:
            conn.close()
            return {"ok": False, "error": "is_evergreen must be 0 or 1"}
        updates["is_evergreen"] = is_evergreen
    if status is not None:
        normalized_status, status_error = _normalized_enum_value(status, _ACTIVITY_STATUSES)
        if status_error:
            conn.close()
            return {"ok": False, "error": status_error}
        updates["status"] = normalized_status
    if weather_sensitive is not None:
        updates["weather_sensitive"] = weather_sensitive
    if physical_intensity is not None:
        updates["physical_intensity"] = physical_intensity
    if repeatability_factor is not None:
        if repeatability_factor <= 0:
            conn.close()
            return {"ok": False, "error": "repeatability_factor must be greater than 0"}
        updates["repeatability_factor"] = float(repeatability_factor)
    if available_days is not None:
        day_of_week_mask, day_parse_error = _available_days_to_mask(available_days)
        if day_parse_error:
            conn.close()
            return {"ok": False, "error": day_parse_error}
        updates["day_of_week_mask"] = day_of_week_mask

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
