# retirement-assistant

Retirement assistant is a personal planning tool for day-to-day retirement activities.

It combines:
- A SQLite database for activities, appointments, timed events, annual recurring events, and activity history
- A Python MCP server with natural-language tools for Copilot
- A lightweight setup script for database initialization and maintenance

The assistant can:
- Build a daily briefing with appointments, active timed events, annual reminders, and activity suggestions
- Build a separate template-driven planner mode with templates, anchors, and persisted daily plans
- Include annual recurring reminders on the day-of and in advance
- Log completed activities and avoid repeating recently completed ones
- Apply activity-suggestion filters based on readiness, weather sensitivity, rain chance, and temperature
- Respect per-activity weekday availability when suggesting activities
- Return at most one suggestion per activity category to improve variety
- Apply a per-activity repeatability factor to extend or shorten the post-completion cooldown window
- Manage activity metadata (category, intensity, links, notes)

## Structure

```
retirement-assistant/
├── .github/
│   └── copilot-instructions.md
├── .vscode/
│   └── mcp.json
├── db/
│   └── schema.sql
├── documentation/
│   ├── design.md
│   ├── todo.md
│   └── troubleshooting.md
├── mcp/
│   └── server.py
├── scripts/
│   └── setup_db.py
├── tests/
│   ├── conftest.py
│   ├── test_activity_crud.py
│   ├── test_appointment_crud.py
│   ├── test_daily_briefing.py
│   ├── test_timed_event_crud.py
│   └── test_weekday_constraints.py
├── LICENSE
├── pytest.ini
├── README.md
├── settings.example.json
├── settings.local.json
├── requirements.txt
└── .gitignore
```

## Documentation

- [Project Design](documentation/design.md)
- [Troubleshooting Guide](documentation/troubleshooting.md)

## Core Concepts

The canonical domain model used for implementation and AI-assisted changes is maintained in the Conceptual Model section of [Project Design](documentation/design.md#conceptual-model-source-of-truth).

## Local Settings

Use `settings.local.json` for personalized local paths and environment-specific values.

Suggested storage locations:
- `~/OneDrive/Assistant`
- `~/Documents/Assistant`
- Any local folder you control and back up regularly

Typical local overrides include:
- `data_root`: your personal storage folder
- `db_path`: your local SQLite file path
- `weather`: location and timezone values for daily briefing weather lookup
- `ranking`: weighting knobs for activity suggestion ranking

Keep `settings.local.json` out of source control (it is already git-ignored).

## Quick Start

1. Install dependencies:

	```powershell
	.\.venv\Scripts\python.exe -m pip install -r requirements.txt
	```

2. Initialize the database:

	```powershell
	.\.venv\Scripts\python.exe scripts/setup_db.py
	```

3. Start the MCP server (stdio):

	```powershell
	.\.venv\Scripts\python.exe mcp/server.py
	```

4. Use MCP prompts in Copilot chat to add and manage data (see examples below).

If you already have a local database, rerunning the setup command is also the current way to apply schema additions:

```powershell
.\.venv\Scripts\python.exe scripts/setup_db.py
```

## Run Unit Tests

The test suite uses a temporary SQLite database per test run and only synthetic fixture data.
It does not use your working database.

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Common scoped test commands:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_activity_crud.py
.\.venv\Scripts\python.exe -m pytest tests/test_appointment_crud.py
.\.venv\Scripts\python.exe -m pytest tests/test_timed_event_crud.py
.\.venv\Scripts\python.exe -m pytest tests/test_daily_briefing.py tests/test_weekday_constraints.py
```

## Notes

- `settings.local.json` is git-ignored to keep personal/local values out of the repository.
- SQLite database files (`*.db`, `*.sqlite`, `*.sqlite3`) are ignored.

## Copilot Command-Style Workflow

GitHub Copilot does not currently provide Claude-style custom slash command routing like `/tasks add` out of the box.
The closest equivalent is MCP tools plus short natural-language command patterns.

After the MCP server is running, you can type prompts like:

- Add appointment title "Dentist" at "2026-06-17T09:00" end "2026-06-17T10:00" location "Main St Clinic" notes "Bring insurance card"
- List appointments for "2026-06-17"
- List appointments from "2026-06-17" to "2026-06-23"
- Update appointment id 1 location "Main St Clinic" notes "Bring insurance card"
- Delete appointment id 1
- Add timed event title "Summer Festival" start "2026-06-23" end "2026-06-28" description "Community event"
- List timed events from "2026-06-23" to "2026-06-28"
- Update timed event id 1 url "https://example.com/festival" status "active"
- Delete timed event id 1
- Add annual event title "Microsoft hire anniversary" event_date "2008-04-07" description "Celebrate" reminder_days_before 7
- List annual events
- List annual events status "active"
- Update annual event id 1 status "inactive"
- Delete annual event id 1
- Add activity title "Morning Walk" category "outdoor" activity_type "landmark" city "Issaquah" location_detail "Watershed Trail" is_evergreen 1 status "active" weather_sensitive 1 physical_intensity 1 urls ["https://example.com/trail"]
- Update activity id 1 location "Watershed Trailhead" activity_type "landmark" city "Issaquah" location_detail "Trailhead lot" is_evergreen 1 status "active" repeatability_factor 1 available_days ["thursday", "saturday"] urls ["https://example.com/parking", "https://example.com/map"]
- Give me details for activity 1
- Give me activity details for "Visit Grateful Bread"
- Delete activity id 1
- Get daily briefing for 2026-06-10 rain_chance 40 readiness 25
- Log activity id 3 status done notes "30 minute walk"
- Get daily briefing for 2026-06-09

Available MCP tools now include:

- `get_daily_briefing`
- `log_activity`
- `add_appointment`
- `list_appointments`
- `update_appointment`
- `delete_appointment`
- `add_timed_event`
- `list_timed_events`
- `update_timed_event`
- `delete_timed_event`
- `add_annual_event`
- `list_annual_events`
- `update_annual_event`
- `delete_annual_event`
- `add_activity`
- `update_activity`
- `delete_activity`
- `get_activity_details`
- `add_template`
- `list_templates`
- `update_template`
- `delete_template`
- `add_template_slot`
- `list_template_slots`
- `update_template_slot`
- `delete_template_slot`
- `add_anchor`
- `list_anchors`
- `update_anchor`
- `delete_anchor`
- `generate_anchor_options`
- `commit_daily_plan`
- `get_daily_plan`
- `list_daily_plans`

## Planner Mode

Planner mode currently coexists with the legacy daily briefing.

The current planner flow is:
1. Create a template.
2. Add one or more template slots.
3. Create an anchor that points at the template.
4. Generate anchor options for a date.
5. Commit a daily plan for the selected anchor.
6. Review the persisted plan.

Planner slot filling uses explicit `activity_type` and city data. For `anchor_city` slots, activities must have an explicit city match.

## Creating A Template

Minimal example workflow:

1. Create a template:

```text
Add template name "Old Town Wander" description "Coffee and walking day"
```

2. Add slots to the template:

```text
Add template slot template_id 1 slot_order 1 slot_type "eatery" required 1 location_scope "anchor_city"
Add template slot template_id 1 slot_order 2 slot_type "landmark" required 0 location_scope "anchor_city"
Add template slot template_id 1 slot_order 3 slot_type "errand" required 0 location_scope "anchor_city" fallback_slot_type "cozy_task"
```

3. Create an anchor using that template:

```text
Add anchor name "Issaquah Morning" city "Issaquah" template_id 1 duration "half_day"
```

4. Preview anchor choices for a date:

```text
Generate anchor options for 2026-07-18
```

5. Commit the plan:

```text
Commit daily plan for 2026-07-18 selected_anchor_id 1
```

6. Review the saved plan:

```text
Get daily plan for 2026-07-18
```

Notes:
- `generate_anchor_options` returns mandatory-appointment context when hard appointment rules apply.
- `commit_daily_plan` stores exactly one plan per date; committing again for the same date replaces the prior plan.
- Slot filling is currently deterministic and picks the first eligible matching activity.

## Automatic Weather In Daily Briefing

`get_daily_briefing` can now auto-fill rain chance and daily temperature range using the free Open-Meteo API.

Configuration in `settings.local.json`:

```json
"weather": {
	"enabled": true,
	"latitude": 47.4502,
	"longitude": -122.3088,
	"timezone": "America/Los_Angeles"
}
```

Behavior:

- If `rain_chance` is passed explicitly, that value is used for filtering activity suggestions.
- If `rain_chance` is omitted, the server uses weather lookup rain chance when available.
- Response now includes a `weather` object with `rain_chance`, `temperature_c_max`, `temperature_c_min`, `temperature_f_max`, `temperature_f_min`, and `source`.
- Response now includes an `annual_reminders` array with recurring anniversary notifications.
- Activity suggestion filtering and selection details, including cooldowns, weekday availability, category diversity, and temperature-aware rules, are documented in [Project Design](documentation/design.md).
- If weather lookup is disabled or unavailable, briefing still works with `weather: null`.

## Activity Suggestion Ranking Weights

Weighted ranking for activity suggestions is configurable via settings.

Planned score formula:

```text
score = (novelty_weight * novelty_score)
      + (city_recency_weight * city_recency_score)
      + (activity_recency_weight * activity_recency_score)
```

Signal meanings:
- `novelty_score`: `1.0` when an activity has never been logged; otherwise `0.0`.
- `city_recency_score`: gradual `0.0..1.0` scale based on days since the city was last visited, capped by `ranking.city_recency_window_days`.
- `activity_recency_score`: gradual `0.0..1.0` scale based on days since the activity was last done, capped by the same recency window.

Important:
- Activity cooldown (`briefing_lookback_days * repeatability_factor`) remains a hard eligibility filter before ranking.
- Ranking weights change preference among eligible candidates; they are not hard include/exclude switches.

Ranking keys in `settings.local.json` (with defaults in `settings.example.json`):

```json
"ranking": {
	"enabled": false,
	"novelty_weight": 0.6,
	"city_recency_weight": 0.3,
	"activity_recency_weight": 0.1,
	"city_recency_window_days": 30,
	"random_seed": null
}
```

Valid user value guidance:
- `ranking.enabled`: boolean (`true` or `false`).
- Weight values (`novelty_weight`, `city_recency_weight`, `activity_recency_weight`): non-negative numbers.
- `ranking.city_recency_window_days`: positive integer (recommended `>= 1`).
- `ranking.random_seed`: optional integer for reproducible selection, primarily useful in testing.

Does the final score need to equal `1`?
- No. The final score does not need to equal `1`.
- If weights sum to `1.0`, max score is `1.0` when all component scores are `1.0`.
- If weights sum to another value, max score scales to that sum.
- Relative score differences drive ranking; exact absolute score value is less important.

Practical recommendation:
- Keep weights non-negative and close to summing to `1.0` for easier tuning and interpretation.

---

A Curious Creations project by Christine Johnson  
Copyright © 2026 Christine Johnson

If this project sparks ideas or you'd like to connect,  
you're welcome to reach out on [LinkedIn](https://www.linkedin.com/in/chrisjohnsonwa).

This repository is public for reference and inspiration.
Issues and pull requests are intentionally disabled.
