from __future__ import annotations


def test_add_activity_creates_activity(isolated_server):
    server, _ = isolated_server

    result = server.add_activity(
        title="Explore Issaquah Front Street",
        description="Walk the old town district",
        location="Issaquah",
        category="old town wandering",
        activity_type="landmark",
        city="Issaquah",
        location_detail="Front Street",
        is_evergreen=1,
        status="active",
        weather_sensitive=1,
        physical_intensity=2,
        repeatability_factor=2,
        available_days=["friday", "saturday"],
        urls=["https://visitissaquahwa.com"],
    )

    assert result["ok"] is True
    assert result["id"] > 0
    assert result["activity"]["title"] == "Explore Issaquah Front Street"
    assert result["activity"]["activity_type"] == "landmark"
    assert result["activity"]["city"] == "Issaquah"
    assert result["activity"]["location_detail"] == "Front Street"
    assert result["activity"]["is_evergreen"] == 1
    assert result["activity"]["status"] == "active"
    assert result["activity"]["available_days"] == ["friday", "saturday"]
    assert result["activity"]["urls"] == ["https://visitissaquahwa.com"]


def test_get_activity_details_returns_activity_with_log_fields(isolated_server):
    server, _ = isolated_server
    created = server.add_activity(title="Station walk")

    details = server.get_activity_details(activity_id=created["id"])

    assert details["ok"] is True
    assert details["activity"]["id"] == created["id"]
    assert details["activity"]["title"] == "Station walk"
    assert details["activity"]["last_visited_date"] is None
    assert details["activity"]["latest_log_date"] is None


def test_update_activity_updates_scalar_and_url_fields(isolated_server):
    server, _ = isolated_server
    created = server.add_activity(
        title="Coffee run",
        description="Before update",
        location="Old place",
        urls=["https://example.com/old"],
    )

    updated = server.update_activity(
        activity_id=created["id"],
        title="Coffee and pastry run",
        description="",
        location="New place",
        category="cafe",
        activity_type="eatery",
        city="Sammamish",
        location_detail="Pine Lake",
        is_evergreen=0,
        status="retired",
        weather_sensitive=0,
        physical_intensity=1,
        repeatability_factor=3,
        available_days="sunday",
        urls=["https://example.com/new"],
    )

    assert updated["ok"] is True
    activity = updated["activity"]
    assert activity["title"] == "Coffee and pastry run"
    assert activity["description"] is None
    assert activity["location"] == "New place"
    assert activity["category"] == "cafe"
    assert activity["activity_type"] == "eatery"
    assert activity["city"] == "Sammamish"
    assert activity["location_detail"] == "Pine Lake"
    assert activity["is_evergreen"] == 0
    assert activity["status"] == "retired"
    assert activity["repeatability_factor"] == 3.0
    assert activity["available_days"] == ["sunday"]
    assert activity["urls"] == ["https://example.com/new"]


def test_update_activity_rejects_invalid_new_field_values(isolated_server):
    server, _ = isolated_server
    created = server.add_activity(title="Validation checks")

    bad_type = server.update_activity(activity_id=created["id"], activity_type="museum")
    assert bad_type["ok"] is False
    assert "value must be one of" in bad_type["error"]

    bad_status = server.update_activity(activity_id=created["id"], status="inactive")
    assert bad_status["ok"] is False
    assert "value must be one of" in bad_status["error"]

    bad_evergreen = server.update_activity(activity_id=created["id"], is_evergreen=2)
    assert bad_evergreen["ok"] is False
    assert bad_evergreen["error"] == "is_evergreen must be 0 or 1"


def test_log_activity_records_status_and_updates_details(isolated_server):
    server, _ = isolated_server
    created = server.add_activity(title="Neighborhood loop")

    log_result = server.log_activity(
        activity_id=created["id"],
        status="done",
        log_date="2026-07-10",
        notes="Completed after lunch",
    )

    details = server.get_activity_details(activity_id=created["id"])

    assert log_result["ok"] is True
    assert log_result["id"] > 0
    assert details["activity"]["last_visited_date"] == "2026-07-10"
    assert details["activity"]["latest_log_date"] == "2026-07-10"
    assert details["activity"]["latest_log_status"] == "done"
    assert details["activity"]["latest_logged_description"] == "Completed after lunch"


def test_delete_activity_removes_activity(isolated_server):
    server, _ = isolated_server
    created = server.add_activity(title="Archive me")

    deleted = server.delete_activity(activity_id=created["id"])
    details = server.get_activity_details(activity_id=created["id"])

    assert deleted["ok"] is True
    assert deleted["deleted_activity"]["id"] == created["id"]
    assert details["ok"] is False


def test_add_activity_rejects_non_positive_repeatability_factor(isolated_server):
    server, _ = isolated_server

    result = server.add_activity(title="Bad repeatability", repeatability_factor=0)

    assert result["ok"] is False
    assert result["error"] == "repeatability_factor must be greater than 0"


def test_add_activity_accepts_hiking_activity_type(isolated_server):
    server, _ = isolated_server

    result = server.add_activity(
        title="Test trail loop",
        category="Nature Trail",
        activity_type="hiking",
        city="Bellevue",
    )

    assert result["ok"] is True
    assert result["activity"]["activity_type"] == "hiking"
    assert result["activity"]["city"] == "Bellevue"


def test_update_activity_rejects_invalid_available_days(isolated_server):
    server, _ = isolated_server
    created = server.add_activity(title="Day validation")

    result = server.update_activity(activity_id=created["id"], available_days="funday")

    assert result["ok"] is False
    assert "Unrecognized weekday" in result["error"]


def test_delete_activity_returns_not_found_for_missing_id(isolated_server):
    server, _ = isolated_server

    result = server.delete_activity(activity_id=99999)

    assert result == {"ok": False, "error": "Activity 99999 not found"}


def test_get_activity_details_requires_identifier(isolated_server):
    server, _ = isolated_server

    result = server.get_activity_details()

    assert result == {"ok": False, "error": "Provide either activity_id or title"}
