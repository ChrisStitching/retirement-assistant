from __future__ import annotations


def test_template_anchor_and_slot_crud_happy_path(isolated_server):
    server, _ = isolated_server

    template = server.add_template(name="Wander", description="City wander template")
    assert template["ok"] is True
    template_id = template["id"]

    slot = server.add_template_slot(
        template_id=template_id,
        slot_order=1,
        slot_type="eatery",
        required=1,
        location_scope="anchor_city",
    )
    assert slot["ok"] is True
    assert slot["template_slot"]["slot_type"] == "eatery"

    listed_templates = server.list_templates()
    assert listed_templates["ok"] is True
    assert listed_templates["templates"][0]["name"] == "Wander"
    assert listed_templates["templates"][0]["slots"][0]["slot_type"] == "eatery"

    anchor = server.add_anchor(
        name="Issaquah Day",
        city="Issaquah",
        template_id=template_id,
        duration="half_day",
        location_detail="Downtown",
    )
    assert anchor["ok"] is True
    anchor_id = anchor["id"]

    updated_anchor = server.update_anchor(anchor_id=anchor_id, name="Issaquah Full Day", duration="full_day")
    assert updated_anchor["ok"] is True
    assert updated_anchor["anchor"]["duration"] == "full_day"

    updated_slot = server.update_template_slot(slot_id=slot["id"], required=0, location_scope="anywhere")
    assert updated_slot["ok"] is True
    assert updated_slot["template_slot"]["required"] == 0
    assert updated_slot["template_slot"]["location_scope"] == "anywhere"

    listed_slots = server.list_template_slots(template_id=template_id)
    assert listed_slots["ok"] is True
    assert listed_slots["template_slots"][0]["slot_type"] == "eatery"

    deleted_slot = server.delete_template_slot(slot_id=slot["id"])
    deleted_anchor = server.delete_anchor(anchor_id=anchor_id)
    deleted_template = server.delete_template(template_id=template_id)

    assert deleted_slot["ok"] is True
    assert deleted_anchor["ok"] is True
    assert deleted_template["ok"] is True


def test_generate_anchor_options_returns_top_three_active_anchors(isolated_server):
    server, _ = isolated_server

    template = server.add_template(name="Wander Template")
    assert template["ok"] is True

    for index in range(4):
        result = server.add_anchor(
            name=f"Anchor {index}",
            city="Issaquah",
            template_id=template["id"],
            duration="half_day",
        )
        assert result["ok"] is True

    options = server.generate_anchor_options(date="2026-07-18")

    assert options["ok"] is True
    assert options["selection_mode"] == "user_anchor"
    assert len(options["anchor_options"]) == 3
    assert [anchor["name"] for anchor in options["anchor_options"]] == ["Anchor 0", "Anchor 1", "Anchor 2"]


def test_generate_anchor_options_respects_mandatory_appointment_anchor(isolated_server):
    server, _ = isolated_server

    template = server.add_template(name="Wander Template")
    assert template["ok"] is True
    anchor = server.add_anchor(name="Backup Anchor", city="Issaquah", template_id=template["id"], duration="half_day")
    assert anchor["ok"] is True

    appointment = server.add_appointment(
        title="Doctor Visit",
        appt_dt="2026-07-18T09:00",
        appt_end_dt="2026-07-18T10:00",
        planning_disposition="mandatory",
    )
    assert appointment["ok"] is True

    options = server.generate_anchor_options(date="2026-07-18")

    assert options["ok"] is True
    assert options["selection_mode"] == "mandatory_appointment"
    assert options["anchor_options"] == []
    assert options["appointment_anchor"]["title"] == "Doctor Visit"


def test_commit_and_get_daily_plan_skeleton(isolated_server):
    server, db_path = isolated_server

    template = server.add_template(name="Wander Template")
    anchor = server.add_anchor(name="Issaquah Day", city="Issaquah", template_id=template["id"], duration="half_day")

    committed = server.commit_daily_plan(date="2026-07-18", selected_anchor_id=anchor["id"])
    assert committed["ok"] is True
    assert committed["plan"]["plan_date"] == "2026-07-18"
    assert committed["plan"]["anchor_source"] == "user_anchor"
    assert committed["plan"]["anchor"]["id"] == anchor["id"]
    assert committed["plan"]["items"][0]["slot_type"] == "anchor"

    retrieved = server.get_daily_plan(date="2026-07-18")
    assert retrieved["ok"] is True
    assert retrieved["plan"]["plan_date"] == "2026-07-18"

    listed = server.list_daily_plans(start_date="2026-07-18", end_date="2026-07-18")
    assert listed["ok"] is True
    assert len(listed["daily_plans"]) == 1
    assert listed["daily_plans"][0]["anchor_source"] == "user_anchor"


def test_commit_daily_plan_replaces_existing_plan(isolated_server):
    server, _ = isolated_server

    template = server.add_template(name="Wander Template")
    anchor_one = server.add_anchor(name="Anchor One", city="Issaquah", template_id=template["id"], duration="half_day")
    anchor_two = server.add_anchor(name="Anchor Two", city="Issaquah", template_id=template["id"], duration="half_day")

    first = server.commit_daily_plan(date="2026-07-18", selected_anchor_id=anchor_one["id"])
    second = server.commit_daily_plan(date="2026-07-18", selected_anchor_id=anchor_two["id"])

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["plan"]["anchor"]["id"] == anchor_two["id"]

    listed = server.list_daily_plans(start_date="2026-07-18", end_date="2026-07-18")
    assert len(listed["daily_plans"]) == 1
    assert listed["daily_plans"][0]["anchor"]["id"] == anchor_two["id"]


def test_commit_daily_plan_requires_explicit_type_and_city_for_anchor_city_slots(isolated_server):
    server, _ = isolated_server

    template = server.add_template(name="Coffee Morning")
    assert template["ok"] is True

    slot = server.add_template_slot(
        template_id=template["id"],
        slot_order=1,
        slot_type="eatery",
        required=1,
        location_scope="anchor_city",
    )
    assert slot["ok"] is True

    anchor = server.add_anchor(name="Issaquah Morning", city="Issaquah", template_id=template["id"], duration="half_day")
    assert anchor["ok"] is True

    null_city_activity = server.add_activity(
        title="Null City Eatery",
        category="eatery",
        activity_type="eatery",
    )
    assert null_city_activity["ok"] is True

    explicit_match = server.add_activity(
        title="Issaquah Explicit Eatery",
        category="eatery",
        activity_type="eatery",
        city="Issaquah",
        location="Issaquah",
    )
    assert explicit_match["ok"] is True

    committed = server.commit_daily_plan(date="2026-07-18", selected_anchor_id=anchor["id"])

    assert committed["ok"] is True
    plan = committed["plan"]
    assert plan["items"][0]["slot_type"] == "eatery"
    assert plan["items"][0]["activity"]["title"] == "Issaquah Explicit Eatery"
    assert plan["items"][0]["activity"]["activity_type"] == "eatery"
