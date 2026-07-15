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


def test_daily_briefing_ranking_prioritizes_never_logged_activity(isolated_server, monkeypatch):
    server, _ = isolated_server

    monkeypatch.setattr(
        server,
        "_load_settings",
        lambda: {
            "activity_suggestions_per_day": 1,
            "briefing_lookback_days": 7,
            "weather": {"enabled": False},
            "ranking": {
                "enabled": True,
                "novelty_weight": 1.0,
                "city_recency_weight": 0.0,
                "activity_recency_weight": 0.0,
                "city_recency_window_days": 30,
                "random_seed": 42,
            },
        },
    )

    logged_id = server.add_activity(
        title="Synthetic Logged Activity",
        category="coffee",
        location="Redmond",
        repeatability_factor=1,
        physical_intensity=1,
    )["id"]
    novel_id = server.add_activity(
        title="Synthetic Novel Activity",
        category="hiking",
        location="Bellevue",
        repeatability_factor=1,
        physical_intensity=1,
    )["id"]

    server.log_activity(activity_id=logged_id, status="done", log_date="2026-06-10")

    briefing = server.get_daily_briefing(date="2026-07-14", rain_chance=0, readiness=50)
    suggestion_ids = [activity["id"] for activity in briefing["activity_suggestions"]]

    assert suggestion_ids == [novel_id]
    assert logged_id not in suggestion_ids


def test_daily_briefing_ranking_prefers_less_recent_city(isolated_server, monkeypatch):
    server, _ = isolated_server

    monkeypatch.setattr(
        server,
        "_load_settings",
        lambda: {
            "activity_suggestions_per_day": 1,
            "briefing_lookback_days": 7,
            "weather": {"enabled": False},
            "ranking": {
                "enabled": True,
                "novelty_weight": 0.0,
                "city_recency_weight": 1.0,
                "activity_recency_weight": 0.0,
                "city_recency_window_days": 30,
                "random_seed": 7,
            },
        },
    )

    recent_city_anchor = server.add_activity(
        title="Recent City Anchor",
        category="anchor",
        location="Redmond",
        repeatability_factor=1,
        physical_intensity=3,
    )["id"]
    old_city_anchor = server.add_activity(
        title="Old City Anchor",
        category="anchor",
        location="Seattle",
        repeatability_factor=1,
        physical_intensity=3,
    )["id"]

    recent_candidate = server.add_activity(
        title="Recent City Candidate",
        category="coffee",
        location="Redmond",
        repeatability_factor=1,
        physical_intensity=1,
    )["id"]
    old_candidate = server.add_activity(
        title="Old City Candidate",
        category="hiking",
        location="Seattle",
        repeatability_factor=1,
        physical_intensity=1,
    )["id"]

    server.log_activity(activity_id=recent_city_anchor, status="done", log_date="2026-07-13")
    server.log_activity(activity_id=old_city_anchor, status="done", log_date="2026-06-01")

    briefing = server.get_daily_briefing(date="2026-07-14", rain_chance=0, readiness=50)
    suggestion_ids = [activity["id"] for activity in briefing["activity_suggestions"]]

    assert suggestion_ids == [old_candidate]
    assert recent_candidate not in suggestion_ids


def test_daily_briefing_ranking_zero_weights_falls_back_without_errors(isolated_server, monkeypatch):
    server, _ = isolated_server

    monkeypatch.setattr(
        server,
        "_load_settings",
        lambda: {
            "activity_suggestions_per_day": 3,
            "briefing_lookback_days": 7,
            "weather": {"enabled": False},
            "ranking": {
                "enabled": True,
                "novelty_weight": 0.0,
                "city_recency_weight": 0.0,
                "activity_recency_weight": 0.0,
                "city_recency_window_days": 30,
                "random_seed": 123,
            },
        },
    )

    server.add_activity(
        title="Fallback Candidate A",
        category="hiking",
        repeatability_factor=1,
        physical_intensity=1,
    )
    server.add_activity(
        title="Fallback Candidate B",
        category="coffee",
        repeatability_factor=1,
        physical_intensity=1,
    )
    server.add_activity(
        title="Fallback Candidate C",
        category="shopping",
        repeatability_factor=1,
        physical_intensity=1,
    )

    briefing = server.get_daily_briefing(date="2026-07-14", rain_chance=0, readiness=50)
    categories = [_category_key(activity.get("category")) for activity in briefing["activity_suggestions"]]

    assert len(briefing["activity_suggestions"]) > 0
    assert len(categories) == len(set(categories))
