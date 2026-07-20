from __future__ import annotations


def test_add_appointment_creates_appointment(isolated_server):
    server, _ = isolated_server

    result = server.add_appointment(
        title="Doctor checkup",
        appt_dt="2026-07-12T09:00",
        appt_end_dt="2026-07-12T10:00",
        location="Clinic",
        notes="Bring insurance card",
    )

    assert result["ok"] is True
    assert result["id"] > 0
    assert result["appointment"]["title"] == "Doctor checkup"
    assert result["appointment"]["appt_end_dt"] == "2026-07-12T10:00"
    assert result["appointment"]["planning_disposition"] == "optional"
    assert result["appointment"]["duration_class"] == "morning_only"


def test_add_appointment_defaults_end_time_when_omitted(isolated_server):
    server, _ = isolated_server

    result = server.add_appointment(
        title="Default End",
        appt_dt="2026-07-12T09:15",
    )

    assert result["ok"] is True
    assert result["appointment"]["appt_end_dt"] == "2026-07-12T10:15"


def test_list_appointments_returns_items_in_window(isolated_server):
    server, _ = isolated_server
    server.add_appointment(title="A", appt_dt="2026-07-12T08:00")
    server.add_appointment(title="B", appt_dt="2026-07-13T08:00")

    listed = server.list_appointments(start_date="2026-07-12", end_date="2026-07-13")

    assert listed["ok"] is True
    assert listed["start_date"] == "2026-07-12"
    assert listed["end_date"] == "2026-07-13"
    assert [appt["title"] for appt in listed["appointments"]] == ["A", "B"]


def test_update_appointment_updates_and_clears_optional_fields(isolated_server):
    server, _ = isolated_server
    created = server.add_appointment(
        title="Original",
        appt_dt="2026-07-12T11:00",
        appt_end_dt="2026-07-12T12:00",
        location="Room 1",
        notes="Original notes",
    )

    updated = server.update_appointment(
        appointment_id=created["id"],
        title="Updated",
        appt_end_dt="",
        location="",
        notes="",
    )

    assert updated["ok"] is True
    appt = updated["appointment"]
    assert appt["title"] == "Updated"
    assert appt["appt_end_dt"] == "2026-07-12T12:00"
    assert appt["location"] is None
    assert appt["notes"] is None


def test_delete_appointment_removes_appointment(isolated_server):
    server, _ = isolated_server
    created = server.add_appointment(title="To delete", appt_dt="2026-07-12T14:00")

    deleted = server.delete_appointment(appointment_id=created["id"])
    listed = server.list_appointments(start_date="2026-07-12")

    assert deleted["ok"] is True
    assert deleted["deleted_appointment"]["id"] == created["id"]
    assert listed["appointments"] == []


def test_add_appointment_rejects_blank_title(isolated_server):
    server, _ = isolated_server

    result = server.add_appointment(title="   ", appt_dt="2026-07-12T09:00")

    assert result == {"ok": False, "error": "title cannot be empty"}


def test_add_appointment_rejects_invalid_datetime_order(isolated_server):
    server, _ = isolated_server

    result = server.add_appointment(
        title="Invalid order",
        appt_dt="2026-07-12T10:00",
        appt_end_dt="2026-07-12T09:00",
    )

    assert result == {"ok": False, "error": "appt_end_dt must be on or after appt_dt"}


def test_add_appointment_rejects_invalid_planning_disposition(isolated_server):
    server, _ = isolated_server

    result = server.add_appointment(
        title="Bad disposition",
        appt_dt="2026-07-12T10:00",
        planning_disposition="required",
    )

    assert result == {"ok": False, "error": "planning_disposition must be optional or mandatory"}


def test_add_appointment_applies_duration_class_with_split_hour_override(isolated_server, monkeypatch):
    server, _ = isolated_server

    monkeypatch.setattr(
        server,
        "_load_settings",
        lambda: {
            "activity_suggestions_per_day": 3,
            "briefing_lookback_days": 7,
            "weather": {"enabled": False},
            "planner": {
                "appointment_split_hour": 13,
                "default_appointment_duration_minutes": 60,
                "min_travel_buffer_minutes": 45,
            },
        },
    )

    morning = server.add_appointment(
        title="Morning with 13 split",
        appt_dt="2026-07-12T12:00",
        appt_end_dt="2026-07-12T12:30",
    )
    crossing = server.add_appointment(
        title="Crossing with 13 split",
        appt_dt="2026-07-12T12:30",
        appt_end_dt="2026-07-12T13:30",
    )
    afternoon = server.add_appointment(
        title="Afternoon with 13 split",
        appt_dt="2026-07-12T13:15",
        appt_end_dt="2026-07-12T14:15",
    )

    assert morning["appointment"]["duration_class"] == "morning_only"
    assert crossing["appointment"]["duration_class"] == "all_day"
    assert afternoon["appointment"]["duration_class"] == "afternoon_only"


def test_mandatory_appointments_require_minimum_travel_buffer(isolated_server):
    server, _ = isolated_server

    first = server.add_appointment(
        title="Mandatory One",
        appt_dt="2026-07-12T09:00",
        appt_end_dt="2026-07-12T10:00",
        planning_disposition="mandatory",
    )
    second = server.add_appointment(
        title="Mandatory Too Soon",
        appt_dt="2026-07-12T10:30",
        appt_end_dt="2026-07-12T11:00",
        planning_disposition="mandatory",
    )

    assert first["ok"] is True
    assert second == {
        "ok": False,
        "error": "mandatory appointments require at least 45 minutes between appointments",
    }


def test_mandatory_appointments_must_not_overlap(isolated_server):
    server, _ = isolated_server

    first = server.add_appointment(
        title="Mandatory One",
        appt_dt="2026-07-12T09:00",
        appt_end_dt="2026-07-12T10:00",
        planning_disposition="mandatory",
    )
    second = server.add_appointment(
        title="Mandatory Overlap",
        appt_dt="2026-07-12T09:30",
        appt_end_dt="2026-07-12T10:30",
        planning_disposition="mandatory",
    )

    assert first["ok"] is True
    assert second == {"ok": False, "error": "mandatory appointments must not overlap"}


def test_list_appointments_rejects_invalid_range(isolated_server):
    server, _ = isolated_server

    result = server.list_appointments(start_date="2026-07-12", end_date="2026-07-11")

    assert result == {"ok": False, "error": "end_date must be on or after start_date"}


def test_update_appointment_returns_not_found_for_missing_id(isolated_server):
    server, _ = isolated_server

    result = server.update_appointment(appointment_id=99999, title="Updated")

    assert result == {"ok": False, "error": "Appointment 99999 not found"}


def test_delete_appointment_returns_not_found_for_missing_id(isolated_server):
    server, _ = isolated_server

    result = server.delete_appointment(appointment_id=99999)

    assert result == {"ok": False, "error": "Appointment 99999 not found"}
