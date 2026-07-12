from __future__ import annotations

from pathlib import Path


def _category_key(category: str | None) -> str:
    if isinstance(category, str) and category.strip():
        return category.strip().lower()
    return "__uncategorized__"


def test_daily_briefing_uses_temp_database_only(isolated_server):
    server, db_path = isolated_server

    server.add_appointment(
        title="Synthetic Doctor Visit",
        appt_dt="2026-07-10T09:00",
        location="Synthetic Clinic",
        notes="No personal data",
    )

    briefing = server.get_daily_briefing(date="2026-07-10", rain_chance=10, readiness=50)

    assert isinstance(db_path, Path)
    assert db_path.exists()
    assert "pytest" in str(db_path.parent)
    assert len(briefing["appointments"]) == 1
    assert briefing["appointments"][0]["title"] == "Synthetic Doctor Visit"


def test_daily_briefing_excludes_done_activities_within_cooldown(isolated_server):
    server, _ = isolated_server

    trail_id = server.add_activity(
        title="Synthetic Trail Walk",
        category="hiking",
        repeatability_factor=2,
        physical_intensity=1,
    )["id"]
    cafe_id = server.add_activity(
        title="Synthetic Cafe Stop",
        category="coffee",
        repeatability_factor=1,
        physical_intensity=1,
    )["id"]

    server.log_activity(activity_id=trail_id, status="done", log_date="2026-07-09")

    briefing = server.get_daily_briefing(date="2026-07-10", rain_chance=0, readiness=50)
    suggestion_ids = {activity["id"] for activity in briefing["activity_suggestions"]}

    assert trail_id not in suggestion_ids
    assert cafe_id in suggestion_ids


def test_daily_briefing_suggestions_are_unique_by_category(isolated_server):
    server, _ = isolated_server

    server.add_activity(
        title="Synthetic Hike A",
        category="hiking",
        repeatability_factor=1,
        physical_intensity=1,
    )
    server.add_activity(
        title="Synthetic Hike B",
        category="hiking",
        repeatability_factor=1,
        physical_intensity=1,
    )
    server.add_activity(
        title="Synthetic Coffee",
        category="coffee",
        repeatability_factor=1,
        physical_intensity=1,
    )

    briefing = server.get_daily_briefing(date="2026-07-10", rain_chance=0, readiness=50)
    categories = [_category_key(activity.get("category")) for activity in briefing["activity_suggestions"]]

    assert len(categories) == len(set(categories))
