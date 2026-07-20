# Template Planner Overhaul Implementation Plan

## Purpose
Implement the planner overhaul as a new persisted planning mode that coexists with the current daily briefing until cutover.

This plan is implementation-focused and includes schema, MCP behavior, migration strategy, and test coverage requirements.

Detailed schema baseline for implementation:
- `documentation/implementation_plans/schema_delta_template_planner_v1.md`

## Confirmed Decisions
- Planner ships as a separate mode first; replaces briefing flow later.
- Exactly one persisted daily plan per date.
- Regeneration replaces existing same-date plan (no version history in this phase).
- User selects anchor from 2-3 options before plan generation is committed.
- Appointment classification uses configurable split hour.
- Missing appointment end defaults to start plus configurable duration (default 60 minutes).
- Mandatory appointments are hard constraints.
- Mandatory appointments must not overlap and must satisfy fixed minimum travel buffer.
- Default travel buffer is 45 minutes.
- Multiple mandatory appointments on one date force all-day appointment-anchor behavior and suppress optional template components.
- Activities are reusable components but only surfaced through template slot filling in planner mode.
- Scout follow-up generation is user-directed, not automatic.

## Scope
In scope:
- Planner data model and migrations.
- Planner MCP tool surface.
- Appointment planner rules and validations.
- Persisted daily plan generation and evening check-in.
- Scout lifecycle outcomes with retained history.
- Coexistence with existing daily briefing.

Out of scope (for this phase):
- Location-aware travel-time estimation.
- Plan version history.
- Automatic scout follow-up generation.
- Evening-only appointment class.

## Target Schema Changes

## 1) Existing table updates
1. `appointments`
- Add `planning_disposition` (`mandatory` or `optional`, default `optional`).
- Continue to store `appt_dt` and `appt_end_dt`; classify appointment period in logic.

2. `activities`
- Add `activity_type` (`eatery`, `landmark`, `geocache`, `errand`, `cozy_task`, `scout`).
- Add `is_evergreen` (`0/1`, default `1`).
- Add `status` (`active` or `retired`, default `active`).
- Add normalized location column(s), minimum: `city`.

## 2) New planner tables
1. `anchors`
- id, name, city, location_detail, duration, template_id, status, created_at.

2. `templates`
- id, name, description, status, created_at.

3. `template_slots`
- id, template_id, slot_order, slot_type, required, location_scope, fallback_slot_type.

4. `daily_plans`
- id, plan_date (unique), plan_state, anchor_source, anchor_ref_id, created_at, updated_at.

5. `daily_plan_items`
- id, daily_plan_id, slot_type, activity_id (nullable), status, completion_notes, was_fallback, created_at.

## 3) Migration protocol
For each schema change, update all of:
- `db/schema.sql`
- `scripts/setup_db.py`
- runtime migration in `mcp/server.py`
- relevant MCP queries/mappings/validations in `mcp/server.py`
- tests and documentation

## Settings Contract Additions
Add planner settings in `settings.example.json`:
- `planner.appointment_split_hour = 12`
- `planner.default_appointment_duration_minutes = 60`
- `planner.min_travel_buffer_minutes = 45`

Allow local override in `settings.local.json` (for example split hour `13`).

## MCP Tool Plan

## Phase A: Planner catalogs
- `add_anchor`, `list_anchors`, `update_anchor`, `delete_anchor`
- `add_template`, `list_templates`, `update_template`, `delete_template`
- `add_template_slot`, `update_template_slot`, `delete_template_slot`

## Phase B: Planner generation workflow
- `generate_anchor_options(date)`
- `commit_daily_plan(date, selected_anchor_id)`
- `get_daily_plan(date)`
- `list_daily_plans(start_date?, end_date?)`

Behavior:
- `generate_anchor_options` enforces hard appointment restrictions before returning 2-3 options.
- `commit_daily_plan` persists the selected anchor plan and atomically replaces any existing same-date plan.

## Phase C: Check-in and scout outcomes
- `check_in_daily_plan(date, item_updates)`
- Optional helper: `resolve_scout_outcomes(activity_id, actions)`

Behavior:
- Record done/skipped per plan item.
- Retire non-evergreen completed scout/errand/geocache activities from active pool.
- Preserve logs/history.
- Apply user-selected scout outcomes:
  - create new scout/activity
  - retire scout
  - convert scout to activity and/or anchor

## Phase D: Appointment validations
Integrate into appointment add/update paths:
- End defaulting when missing.
- Boundary classification from `planner.appointment_split_hour`.
- Mandatory overlap rejection.
- Mandatory travel-buffer validation using fixed minutes.

## Coexistence and Cutover Plan
1. Keep existing `get_daily_briefing` behavior unchanged during planner implementation.
2. Add planner tools and tests without breaking existing flows.
3. Validate planner correctness and deterministic constraints.
4. Define cutover readiness criteria:
- planner feature parity for daily usage,
- stable tests,
- no regressions in briefing tests,
- documentation complete.
5. Replace briefing activity suggestion flow only after readiness criteria pass.

## Test Plan

## 1) Schema and migration tests
- Verify new columns/tables created on fresh DB.
- Verify runtime and setup migrations upgrade existing DBs without data loss.
- Verify defaults (`planner` settings fallback behavior).

## 2) Appointment behavior tests
- Missing end time defaults to start + 60 minutes.
- Split-hour classification:
  - before boundary => morning_only
  - after boundary => afternoon_only
  - crossing boundary => all_day
- Split hour override from local settings.
- Mandatory overlap rejection.
- Mandatory travel-buffer rejection when gap < 45 minutes.

## 3) Planner catalog CRUD tests
- Anchor CRUD success/failure paths.
- Template CRUD success/failure paths.
- Slot CRUD ordering/validation tests.

## 4) Anchor option and commit tests
- No mandatory appointments: returns 2-3 anchor options.
- Morning mandatory appointment: hard anchor behavior.
- Afternoon mandatory appointment: restricted morning options.
- Multiple mandatory appointments: all-day multi-appointment template behavior.
- Commit persists exactly one plan for date.
- Regeneration replaces existing same-date plan.

## 5) Slot filling tests
- Required slot fill success.
- Optional slot missing behavior.
- Fallback slot behavior correctness.
- Location-scope matching behavior (`anchor_city`, `anywhere`, `exact_location`).

## 6) Check-in and lifecycle tests
- Check-in updates item statuses and plan state.
- Completed non-evergreen scout/errand/geocache becomes retired.
- Evergreen items remain active.
- History remains queryable after retirement.

## 7) Scout outcome tests
- Create new scouts/activities from completion flow.
- Retire-only outcome.
- Convert-to-activity outcome.
- Convert-to-anchor outcome.
- Combined outcome support in one operation.

## 8) Regression tests for legacy briefing
- Existing tests in:
  - `tests/test_daily_briefing.py`
  - `tests/test_activity_crud.py`
  - `tests/test_appointment_crud.py`
  - `tests/test_timed_event_crud.py`
  - `tests/test_weekday_constraints.py`
- Ensure planner additions do not alter current daily briefing outputs until explicit cutover.

## Suggested Execution Order
1. Schema and migration scaffolding.
2. Planner setting load/validation.
3. Appointment behavior updates and tests.
4. Catalog CRUD tools and tests.
5. Anchor option and commit workflow.
6. Check-in and scout outcome workflow.
7. Coexistence validation and documentation sync.

## Done Criteria
- Planner tools and schema implemented with deterministic tests passing.
- Existing briefing tests still pass.
- Documentation updated in:
  - `documentation/template_revision_spec.md`
  - `documentation/design.md`
  - this implementation plan file
- Settings defaults and behavior documented and consistent with implementation.
