# Schema Delta for Template Planner (v1)

## Purpose
Define the concrete schema delta from the current SQLite model to planner mode, including migration-safe DDL and validation checks.

This file is a design-to-implementation artifact. It does not change runtime behavior by itself.

## Current Baseline
Current schema source: db/schema.sql

Existing tables:
- appointments
- timed_events
- annual_events
- activities
- activity_urls
- activity_log

## Delta Summary

## 1) Existing table changes

### 1.1 appointments
Add planner disposition metadata for hard vs soft planner behavior.

Proposed column:
- planning_disposition TEXT NOT NULL DEFAULT 'optional'

Allowed values:
- optional
- mandatory

DDL for migration path:
```sql
ALTER TABLE appointments ADD COLUMN planning_disposition TEXT NOT NULL DEFAULT 'optional';
```

Validation check (app-level and/or trigger later):
```sql
CHECK (planning_disposition IN ('optional', 'mandatory'))
```

Notes:
- Appointment classification (morning_only, afternoon_only, all_day) is derived in MCP logic from appt_dt, appt_end_dt, and configured split hour.
- If appt_end_dt is missing at write time, MCP will set appt_end_dt = appt_dt + default minutes.

### 1.2 activities
Add planner component semantics while preserving existing briefing fields.

Proposed columns:
- activity_type TEXT
- city TEXT
- location_detail TEXT
- is_evergreen INTEGER NOT NULL DEFAULT 1
- status TEXT NOT NULL DEFAULT 'active'

DDL for migration path:
```sql
ALTER TABLE activities ADD COLUMN activity_type TEXT;
ALTER TABLE activities ADD COLUMN city TEXT;
ALTER TABLE activities ADD COLUMN location_detail TEXT;
ALTER TABLE activities ADD COLUMN is_evergreen INTEGER NOT NULL DEFAULT 1;
ALTER TABLE activities ADD COLUMN status TEXT NOT NULL DEFAULT 'active';
```

Normalization backfill (first-pass):
```sql
UPDATE activities
SET city = trim(substr(coalesce(location, ''), 1, instr(coalesce(location, '') || ',', ',') - 1))
WHERE city IS NULL AND location IS NOT NULL;

UPDATE activities
SET location_detail = location
WHERE location_detail IS NULL AND location IS NOT NULL;
```

Validation checks (app-level and/or trigger later):
```sql
CHECK (activity_type IS NULL OR activity_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout'))
CHECK (is_evergreen IN (0, 1))
CHECK (status IN ('active', 'retired'))
```

Notes:
- Keep existing category/weather_sensitive/physical_intensity/repeatability_factor/day_of_week_mask for coexistence with get_daily_briefing.
- Planner code should only consume active records where activity_type is not null.

## 2) New planner tables

### 2.1 templates
```sql
CREATE TABLE IF NOT EXISTS templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TEXT DEFAULT (datetime('now')),
    CHECK (status IN ('active', 'inactive'))
);
```

### 2.2 anchors
```sql
CREATE TABLE IF NOT EXISTS anchors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    city            TEXT NOT NULL,
    location_detail TEXT,
    duration        TEXT NOT NULL,
    template_id     INTEGER NOT NULL REFERENCES templates(id),
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT DEFAULT (datetime('now')),
    CHECK (duration IN ('half_day', 'full_day')),
    CHECK (status IN ('active', 'inactive'))
);
```

### 2.3 template_slots
```sql
CREATE TABLE IF NOT EXISTS template_slots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id        INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    slot_order         INTEGER NOT NULL,
    slot_type          TEXT NOT NULL,
    required           INTEGER NOT NULL DEFAULT 0,
    location_scope     TEXT NOT NULL DEFAULT 'anchor_city',
    fallback_slot_type TEXT,
    created_at         TEXT DEFAULT (datetime('now')),
    CHECK (slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout')),
    CHECK (required IN (0, 1)),
    CHECK (location_scope IN ('anchor_city', 'anywhere', 'exact_location')),
    CHECK (fallback_slot_type IS NULL OR fallback_slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout')),
    UNIQUE (template_id, slot_order)
);
```

### 2.4 daily_plans
```sql
CREATE TABLE IF NOT EXISTS daily_plans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date     TEXT NOT NULL,
    plan_state    TEXT NOT NULL DEFAULT 'active',
    anchor_source TEXT NOT NULL,
    anchor_ref_id INTEGER,
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now')),
    CHECK (plan_state IN ('draft', 'active', 'checked_in')),
    CHECK (anchor_source IN ('user_anchor', 'mandatory_appointment', 'multi_mandatory_appointments')),
    UNIQUE (plan_date)
);
```

### 2.5 daily_plan_items
```sql
CREATE TABLE IF NOT EXISTS daily_plan_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_plan_id    INTEGER NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    slot_type        TEXT NOT NULL,
    activity_id      INTEGER REFERENCES activities(id),
    status           TEXT NOT NULL DEFAULT 'planned',
    completion_notes TEXT,
    was_fallback     INTEGER NOT NULL DEFAULT 0,
    source_type      TEXT NOT NULL DEFAULT 'template_slot',
    source_ref_id    INTEGER,
    created_at       TEXT DEFAULT (datetime('now')),
    CHECK (slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout', 'appointment', 'anchor')),
    CHECK (status IN ('planned', 'done', 'skipped', 'canceled')),
    CHECK (was_fallback IN (0, 1)),
    CHECK (source_type IN ('template_slot', 'appointment', 'anchor'))
);
```

## 3) New indexes
```sql
CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(date(appt_dt));
CREATE INDEX IF NOT EXISTS idx_appointments_disposition_date ON appointments(planning_disposition, date(appt_dt));

CREATE INDEX IF NOT EXISTS idx_activities_type_status_city ON activities(activity_type, status, city);
CREATE INDEX IF NOT EXISTS idx_templates_status ON templates(status);
CREATE INDEX IF NOT EXISTS idx_anchors_status_city ON anchors(status, city);

CREATE INDEX IF NOT EXISTS idx_daily_plans_date ON daily_plans(plan_date);
CREATE INDEX IF NOT EXISTS idx_daily_plan_items_plan ON daily_plan_items(daily_plan_id);
CREATE INDEX IF NOT EXISTS idx_daily_plan_items_activity ON daily_plan_items(activity_id);
```

## 4) Atomic replacement pattern for one plan per day
Use transaction pattern in MCP commit flow:
```sql
BEGIN;

DELETE FROM daily_plan_items
WHERE daily_plan_id IN (SELECT id FROM daily_plans WHERE plan_date = :plan_date);

DELETE FROM daily_plans
WHERE plan_date = :plan_date;

INSERT INTO daily_plans (plan_date, plan_state, anchor_source, anchor_ref_id)
VALUES (:plan_date, 'active', :anchor_source, :anchor_ref_id);

-- insert daily_plan_items rows

COMMIT;
```

## 5) Compatibility and coexistence notes
- Do not remove or repurpose existing briefing fields during planner rollout.
- Planner and briefing can share activities table while using different field subsets.
- Existing activity_log remains the shared history trail for activity outcomes.
- daily_plan_items adds per-plan status history; this is not full plan revision history.

## 6) Migration order (code implementation)
1. Update db/schema.sql with new columns/tables/indexes.
2. Update scripts/setup_db.py migrate_schema() to add missing columns/tables/indexes for existing DBs.
3. Update mcp/server.py runtime _migrate_schema() with matching compatibility path.
4. Backfill minimal city/location_detail values for existing activities.
5. Add MCP validations for constrained values.
6. Add tests for fresh-init and migrate-existing-db scenarios.

## 7) Schema test checklist
- Fresh DB contains all new planner columns/tables/indexes.
- Existing DB migration adds columns without data loss.
- Existing rows get defaults:
  - appointments.planning_disposition => optional
  - activities.is_evergreen => 1
  - activities.status => active
- Constraint checks reject invalid enum-like values at MCP validation layer.
- Unique plan_date enforced in daily_plans.
- Cascading delete from daily_plans to daily_plan_items works.
