PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS appointments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    location    TEXT,
    appt_dt     TEXT NOT NULL,
    appt_end_dt TEXT,
    planning_disposition TEXT NOT NULL DEFAULT 'optional' CHECK (planning_disposition IN ('optional', 'mandatory')),
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS timed_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT,
    url         TEXT,
    start_date  TEXT NOT NULL,
    end_date    TEXT NOT NULL,
    status      TEXT DEFAULT 'active',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS annual_events (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    title                   TEXT NOT NULL,
    event_date              TEXT NOT NULL,
    description             TEXT,
    reminder_days_before    INTEGER DEFAULT 7,
    status                  TEXT DEFAULT 'active',
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activities (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    title               TEXT NOT NULL,
    description         TEXT,
    location            TEXT,
    category            TEXT,
    activity_type       TEXT CHECK (activity_type IS NULL OR activity_type IN ('eatery', 'landmark', 'hiking', 'geocache', 'errand', 'cozy_task', 'scout')),
    city                TEXT,
    location_detail     TEXT,
    is_evergreen        INTEGER NOT NULL DEFAULT 1 CHECK (is_evergreen IN (0, 1)),
    status              TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'retired')),
    weather_sensitive   INTEGER DEFAULT 0,
    physical_intensity  INTEGER DEFAULT 1,
    repeatability_factor REAL DEFAULT 2,
    day_of_week_mask    INTEGER
);

CREATE TABLE IF NOT EXISTS activity_urls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    url         TEXT NOT NULL,
    label       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id INTEGER REFERENCES activities(id),
    log_date    TEXT NOT NULL,
    status      TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS templates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS anchors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    city            TEXT NOT NULL,
    location_detail TEXT,
    duration        TEXT NOT NULL CHECK (duration IN ('half_day', 'full_day')),
    template_id     INTEGER NOT NULL REFERENCES templates(id),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS template_slots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id        INTEGER NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
    slot_order         INTEGER NOT NULL,
    slot_type          TEXT NOT NULL CHECK (slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout')),
    required           INTEGER NOT NULL DEFAULT 0 CHECK (required IN (0, 1)),
    location_scope     TEXT NOT NULL DEFAULT 'anchor_city' CHECK (location_scope IN ('anchor_city', 'anywhere', 'exact_location')),
    fallback_slot_type TEXT CHECK (fallback_slot_type IS NULL OR fallback_slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout')),
    created_at         TEXT DEFAULT (datetime('now')),
    UNIQUE (template_id, slot_order)
);

CREATE TABLE IF NOT EXISTS daily_plans (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_date     TEXT NOT NULL UNIQUE,
    plan_state    TEXT NOT NULL DEFAULT 'active' CHECK (plan_state IN ('draft', 'active', 'checked_in')),
    anchor_source TEXT NOT NULL CHECK (anchor_source IN ('user_anchor', 'mandatory_appointment', 'multi_mandatory_appointments')),
    anchor_ref_id INTEGER,
    created_at    TEXT DEFAULT (datetime('now')),
    updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_plan_items (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    daily_plan_id    INTEGER NOT NULL REFERENCES daily_plans(id) ON DELETE CASCADE,
    slot_type        TEXT NOT NULL CHECK (slot_type IN ('eatery', 'landmark', 'geocache', 'errand', 'cozy_task', 'scout', 'appointment', 'anchor')),
    activity_id      INTEGER REFERENCES activities(id),
    status           TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'done', 'skipped', 'canceled')),
    completion_notes TEXT,
    was_fallback     INTEGER NOT NULL DEFAULT 0 CHECK (was_fallback IN (0, 1)),
    source_type      TEXT NOT NULL DEFAULT 'template_slot' CHECK (source_type IN ('template_slot', 'appointment', 'anchor')),
    source_ref_id    INTEGER,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(date(appt_dt));
CREATE INDEX IF NOT EXISTS idx_appointments_disposition_date ON appointments(planning_disposition, date(appt_dt));
CREATE INDEX IF NOT EXISTS idx_activities_type_status_city ON activities(activity_type, status, city);
CREATE INDEX IF NOT EXISTS idx_templates_status ON templates(status);
CREATE INDEX IF NOT EXISTS idx_anchors_status_city ON anchors(status, city);
CREATE INDEX IF NOT EXISTS idx_daily_plans_date ON daily_plans(plan_date);
CREATE INDEX IF NOT EXISTS idx_daily_plan_items_plan ON daily_plan_items(daily_plan_id);
CREATE INDEX IF NOT EXISTS idx_daily_plan_items_activity ON daily_plan_items(activity_id);
