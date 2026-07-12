from __future__ import annotations


def test_add_timed_event_creates_timed_event(isolated_server):
    server, _ = isolated_server

    result = server.add_timed_event(
        title="Summer Fair",
        start_date="2026-07-10",
        end_date="2026-07-20",
        description="Community event",
        url="https://example.com/fair",
    )

    assert result["ok"] is True
    assert result["id"] > 0
    assert result["timed_event"]["title"] == "Summer Fair"
    assert result["timed_event"]["status"] == "active"


def test_list_timed_events_filters_by_window_and_status(isolated_server):
    server, _ = isolated_server
    server.add_timed_event(title="A", start_date="2026-07-10", end_date="2026-07-12")
    second = server.add_timed_event(title="B", start_date="2026-07-15", end_date="2026-07-16")
    server.update_timed_event(timed_event_id=second["id"], status="inactive")

    listed = server.list_timed_events(start_date="2026-07-11", end_date="2026-07-15", status="active")

    assert listed["ok"] is True
    assert listed["start_date"] == "2026-07-11"
    assert listed["end_date"] == "2026-07-15"
    assert listed["status"] == "active"
    assert [event["title"] for event in listed["timed_events"]] == ["A"]


def test_update_timed_event_updates_fields_and_status(isolated_server):
    server, _ = isolated_server
    created = server.add_timed_event(
        title="Original title",
        start_date="2026-07-10",
        end_date="2026-07-11",
        description="Original description",
        url="https://example.com/original",
    )

    updated = server.update_timed_event(
        timed_event_id=created["id"],
        title="Updated title",
        description="",
        url="",
        status="inactive",
    )

    assert updated["ok"] is True
    event = updated["timed_event"]
    assert event["title"] == "Updated title"
    assert event["description"] is None
    assert event["url"] is None
    assert event["status"] == "inactive"


def test_delete_timed_event_removes_timed_event(isolated_server):
    server, _ = isolated_server
    created = server.add_timed_event(title="Delete me", start_date="2026-07-12", end_date="2026-07-13")

    deleted = server.delete_timed_event(timed_event_id=created["id"])
    listed = server.list_timed_events(status="active")

    assert deleted["ok"] is True
    assert deleted["deleted_timed_event"]["id"] == created["id"]
    assert listed["timed_events"] == []


def test_add_timed_event_rejects_invalid_date_range(isolated_server):
    server, _ = isolated_server

    result = server.add_timed_event(
        title="Bad range",
        start_date="2026-07-20",
        end_date="2026-07-10",
    )

    assert result == {"ok": False, "error": "end_date must be on or after start_date"}


def test_list_timed_events_rejects_invalid_status_filter(isolated_server):
    server, _ = isolated_server

    result = server.list_timed_events(status="paused")

    assert result == {"ok": False, "error": "status must be active or inactive"}


def test_update_timed_event_rejects_missing_update_fields(isolated_server):
    server, _ = isolated_server
    created = server.add_timed_event(title="No-op", start_date="2026-07-10", end_date="2026-07-10")

    result = server.update_timed_event(timed_event_id=created["id"])

    assert result == {"ok": False, "error": "No fields provided to update"}


def test_update_timed_event_rejects_invalid_status_value(isolated_server):
    server, _ = isolated_server
    created = server.add_timed_event(title="Status validation", start_date="2026-07-10", end_date="2026-07-10")

    result = server.update_timed_event(timed_event_id=created["id"], status="paused")

    assert result == {"ok": False, "error": "status must be active or inactive"}


def test_delete_timed_event_returns_not_found_for_missing_id(isolated_server):
    server, _ = isolated_server

    result = server.delete_timed_event(timed_event_id=99999)

    assert result == {"ok": False, "error": "Timed event 99999 not found"}
