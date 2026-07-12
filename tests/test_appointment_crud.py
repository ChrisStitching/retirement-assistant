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
    assert appt["appt_end_dt"] is None
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
