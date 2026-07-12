from __future__ import annotations

def test_add_activity_accepts_single_weekday_name(isolated_server):
    server, _ = isolated_server

    result = server.add_activity(
        title="Synthetic Thursday Market",
        category="market",
        weather_sensitive=1,
        physical_intensity=1,
        repeatability_factor=1,
        available_days="thursday",
    )

    assert result["ok"] is True
    assert result["activity"]["available_days"] == ["thursday"]


def test_add_activity_accepts_weekday_array(isolated_server):
    server, _ = isolated_server

    result = server.add_activity(
        title="Synthetic Weekend Market",
        category="market",
        weather_sensitive=1,
        physical_intensity=1,
        repeatability_factor=1,
        available_days=["saturday", "sunday"],
    )

    assert result["ok"] is True
    assert result["activity"]["available_days"] == ["saturday", "sunday"]


def test_daily_briefing_filters_activities_by_available_weekday(isolated_server):
    server, _ = isolated_server

    always_result = server.add_activity(
        title="Synthetic Anyday Walk",
        category="walking",
        weather_sensitive=0,
        physical_intensity=1,
        repeatability_factor=1,
    )
    thursday_result = server.add_activity(
        title="Synthetic Thursday Market",
        category="market",
        weather_sensitive=0,
        physical_intensity=1,
        repeatability_factor=1,
        available_days="thursday",
    )

    assert always_result["ok"] is True
    assert thursday_result["ok"] is True

    thursday_briefing = server.get_daily_briefing(date="2026-07-09", rain_chance=0, readiness=50)
    friday_briefing = server.get_daily_briefing(date="2026-07-10", rain_chance=0, readiness=50)

    thursday_ids = {activity["id"] for activity in thursday_briefing["activity_suggestions"]}
    friday_ids = {activity["id"] for activity in friday_briefing["activity_suggestions"]}

    assert thursday_result["id"] in thursday_ids
    assert thursday_result["id"] not in friday_ids
