# Retirement Assistant Overhaul Specification
### Daily Template Planner • Version 2.0

## 1. Purpose
Move from flat activity suggestions to a persisted, template-driven daily planner that reduces decision friction while preserving spontaneity.

The planner introduces:
- User-managed anchors
- User-managed templates and slots
- Activity components that plug into templates
- Hard appointment override rules
- Persistent daily plans with evening check-in
- Scout lifecycle handling with retained history

## 2. Rollout Strategy
Planner mode ships as a separate mode that coexists with the current daily briefing.

Rollout phases:
1. Planner mode and current briefing both available.
2. Planner mode reaches feature and reliability targets.
3. Planner mode replaces daily briefing flow.

Current ranking/weather/readiness logic remains in the briefing path during coexistence and is reassessed after planner stabilization.

## 3. Core Domain Concepts

### 3.1 Anchor
Anchors are user-managed records that define day shape.

Anchor fields:
- `name`
- `city`
- `location_detail` (optional)
- `duration` (`half_day` or `full_day`)
- `template_id`
- `status` (`active` or `inactive`)

### 3.2 Template
Templates are user-managed records that define slot structure.

Template fields:
- `name`
- `description` (optional)
- `status` (`active` or `inactive`)
- ordered `template_slots`

Template slot fields:
- `slot_type` (`eatery`, `landmark`, `geocache`, `errand`, `cozy_task`, `scout`)
- `required` (`true` or `false`)
- `location_scope` (`anchor_city`, `anywhere`, `exact_location`)
- `fallback_slot_type` (optional)

### 3.3 Activity
Activities are reusable components selected through templates only.

Activity fields (planner-facing):
- `title`
- `activity_type` (`eatery`, `landmark`, `geocache`, `errand`, `cozy_task`, `scout`)
- `city`
- `location_detail` (optional)
- `is_evergreen` (`true` or `false`)
- `status` (`active` or `retired`)
- `metadata` (optional)

Rule:
- Activities are not surfaced as standalone planner suggestions outside a template fill.

### 3.4 Appointment Planning Disposition
Appointments remain in the appointments table and add planner behavior metadata.

Disposition:
- `mandatory`: hard override behavior
- `optional`: treated as time-constrained optional items, not anchors

### 3.5 Daily Plan
Daily plans are persisted records with exactly one row per date.

Daily plan fields:
- `plan_date`
- `plan_state` (`draft`, `active`, `checked_in`)
- `anchor_source` (`user_anchor`, `mandatory_appointment`, `multi_mandatory_appointments`)
- `anchor_ref` (nullable, depending on source)
- generated `daily_plan_items`

Replacement behavior:
- Regeneration replaces the existing same-date plan and item rows atomically.
- Revision history is out of scope for this version.

## 4. Appointment Classification and Hard Rules

### 4.1 Time Classification
Classification uses configured split hour and start/end datetimes.

Config keys:
- `planner.appointment_split_hour`
- `planner.default_appointment_duration_minutes`
- `planner.min_travel_buffer_minutes`

Defaults:
- `settings.example.json`: split hour `12` (noon), default duration `60`, min travel buffer `45`
- `settings.local.json`: split hour may be overridden (current local preference: `13`)

Duration default:
- If `appt_end_dt` is omitted, set it to `appt_dt + planner.default_appointment_duration_minutes`.

Classification rules:
- `morning_only`: start and end both before split boundary
- `afternoon_only`: start and end both after split boundary
- `all_day`: appointment crosses the split boundary

`evening_only` is deferred.

### 4.2 Mandatory Appointment Rules
Mandatory appointment rules are hard constraints.

Rules:
- Mandatory appointments must not overlap.
- Mandatory appointments must satisfy minimum travel buffer between consecutive appointments on the same date.
- A morning mandatory appointment acts as hard anchor source.
- An afternoon mandatory appointment hard-restricts morning anchor options.

### 4.3 Multi-Mandatory-Appointment Day
If multiple mandatory appointments exist on a date:
- All appointments appear in the plan.
- Day is treated as all-day.
- No optional activities or template components are suggested.
- Appointment list itself is the anchor source.
- Planner uses a dedicated multi-appointment-day template behavior.

## 5. Planner Daily Flow

### 5.1 Step 1: Anchor Option Generation
For dates without all-day mandatory constraints:
- Return 2-3 anchor options.
- Apply hard appointment constraints before presenting options.

### 5.2 Step 2: User Anchor Selection and Commit
- User explicitly selects one anchor.
- Planner generates and persists the plan only after selection.
- Planner does not auto-commit anchor choice.

### 5.3 Plan Composition
For selected anchor:
1. Load template and ordered slots.
2. Fill slots from eligible active activities.
3. Respect slot type, location scope, and optional fallback semantics.
4. Persist plan and item snapshots.

### 5.4 Evening Check-In
Planner retrieves persisted plan and prompts completion status per item.

On check-in:
- Mark item outcomes.
- Retire non-evergreen completed components from active pool as appropriate (`geocache`, `errand`, `scout`).
- Keep history trail in logs and plan records.
- Mark plan as checked in.

## 6. Scout Lifecycle
Scouts are one-time exploratory components.

On scout completion, user chooses one or more outcomes:
1. Create new scouts and/or new activities.
2. Retire the scout with no further action.
3. Convert the scout into a mature activity or anchor.

Outcomes are not mutually exclusive.
Follow-up items are not auto-generated.

## 7. Data Model Additions (Target)

### 7.1 Updated Existing Tables
- `appointments`: add planner disposition and derived classification support.
- `activities`: add planner-oriented fields (`activity_type`, `is_evergreen`, `status`, normalized city fields).

### 7.2 New Tables
- `anchors`
- `templates`
- `template_slots`
- `daily_plans`
- `daily_plan_items`

### 7.3 History and Retention
- Use logs and plan-item status history to retain completed/retired trail.
- Prefer soft lifecycle state transitions over hard deletion for completed scouts.

## 8. MCP Behavior Targets
New planner-facing MCP surface should include:
- Anchor CRUD
- Template CRUD and slot CRUD
- Planner plan-generation flow (options then commit)
- Daily plan retrieval/listing
- Check-in with per-item outcomes
- Scout outcome handling utilities

Legacy daily briefing tools remain available during coexistence.

## 9. Non-Goals for Version 2.0
- Location-aware travel-time estimation
- Plan revision history/versioning
- Automatic scout follow-up generation
- Evening-only appointment class

## 10. Future Improvements
- Location-aware travel buffer estimation
- Planner explainability payloads
- Weather-aware template selection
- Seasonal rotations
- Weekly planner analytics