# retirement-assistant

Retirement assistant is a personal planning tool for day-to-day retirement activities.

It combines:
- A SQLite database for activities, appointments, timed events, annual recurring events, and activity history
- A Python MCP server with natural-language tools for Copilot
- A lightweight setup script for database initialization and maintenance

The assistant can:
- Build a daily briefing with appointments, active events, and activity suggestions
- Include annual recurring reminders on the day-of and in advance
- Log completed activities and avoid repeating recently completed ones
- Apply recommendation filters based on readiness, weather sensitivity, rain chance, and temperature
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

Keep `settings.local.json` out of source control (it is already git-ignored).

## Quick Start

1. Install dependencies:

	```powershell
	pip install -r requirements.txt
	```

2. Initialize the database:

	```powershell
	python scripts/setup_db.py
	```

3. Start the MCP server (stdio):

	```powershell
	python mcp/server.py
	```

4. Use MCP prompts in Copilot chat to add and manage data (see examples below).

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
- Add activity title "Morning Walk" category "outdoor" weather_sensitive 1 physical_intensity 1 urls ["https://example.com/trail"]
- Update activity id 1 location "Watershed Trailhead" repeatability_factor 1 available_days ["thursday", "saturday"] urls ["https://example.com/parking", "https://example.com/map"]
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

- If `rain_chance` is passed explicitly, that value is used for filtering suggestions.
- If `rain_chance` is omitted, the server uses weather lookup rain chance when available.
- Response now includes a `weather` object with `rain_chance`, `temperature_c_max`, `temperature_c_min`, `temperature_f_max`, `temperature_f_min`, and `source`.
- Response now includes an `annual_reminders` array with recurring anniversary notifications.
- Activities marked done within the last `briefing_lookback_days` (default 7) are excluded from recommendations.
- Activity cooldown now uses `briefing_lookback_days * repeatability_factor` per activity (default factor `2`, so a default 7-day lookback means 14 days before resuggesting a completed activity).
- Activities can be constrained to specific weekdays using `available_days`; daily briefing only suggests activities valid for the target date's weekday.
- Daily briefing limits suggestions to one activity per category; if fewer categories qualify than requested, fewer suggestions are returned.
- Temperature-aware filtering is applied automatically when weather is available:
	- Motorcycle category activities are excluded when daily high is below 55F.
	- Physical intensity 3 activities are excluded when daily high is above 75F.
	- Weather-sensitive physical intensity 2 activities are excluded when daily high is above 85F.
- If weather lookup is disabled or unavailable, briefing still works with `weather: null`.

---

A Curious Creations project by Christine Johnson  
Copyright © 2026 Christine Johnson

If this project sparks ideas or you'd like to connect,  
you're welcome to reach out on [LinkedIn](https://www.linkedin.com/in/chrisjohnsonwa).

This repository is public for reference and inspiration.
Issues and pull requests are intentionally disabled.
