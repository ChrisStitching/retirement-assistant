# retirement-assistant

Retirement assistant scaffold with:
- SQLite data model
- Python CLI scripts for data entry
- MCP server stub for Copilot Agent tools

## Structure

```
retirement-assistant/
├── .vscode/mcp.json
├── db/schema.sql
├── mcp/server.py
├── scripts/
│   ├── setup_db.py
│   ├── add_appointment.py
│   ├── add_event.py
│   ├── add_activity.py
│   └── update_activity.py
├── settings.example.json
├── settings.local.json
├── requirements.txt
└── .gitignore
```

## Local Settings

This scaffold uses:

`C:/Users/curio/OneDrive/Assistant`

for personal data storage. Your local DB file is configured as:

`C:/Users/curio/OneDrive/Assistant/retirement.db`

## Quick Start

1. Install dependencies:

	```powershell
	pip install -r requirements.txt
	```

2. Initialize the database:

	```powershell
	python scripts/setup_db.py
	```

3. Add sample data:

	```powershell
	python scripts/add_appointment.py --title "Dentist" --appt-dt "2026-06-17T09:00" --location "Main St Clinic"
	python scripts/add_event.py --title "Summer Festival" --start-date "2026-06-23" --end-date "2026-06-28"
	python scripts/add_activity.py --title "Morning Walk" --category "outdoor" --weather-sensitive 1 --physical-intensity 1 --url "https://example.com/trail"
	python scripts/update_activity.py 1 --location "Watershed Trailhead" --url "https://example.com/parking" --url "https://example.com/map"
	```

4. Start the MCP server (stdio):

	```powershell
	python mcp/server.py
	```

## Notes

- `settings.local.json` is git-ignored to keep personal/local values out of the repository.
- SQLite database files (`*.db`, `*.sqlite`, `*.sqlite3`) are ignored.

## Copilot Command-Style Workflow

GitHub Copilot does not currently provide Claude-style custom slash command routing like `/tasks add` out of the box.
The closest equivalent is MCP tools plus short natural-language command patterns.

After the MCP server is running, you can type prompts like:

- Add appointment title "Dentist" at "2026-06-17T09:00" location "Main St Clinic" notes "Bring insurance card"
- Add timed event title "Summer Festival" start "2026-06-23" end "2026-06-28" description "Community event"
- Add activity title "Morning Walk" category "outdoor" weather_sensitive 1 physical_intensity 1 urls ["https://example.com/trail"]
- Update activity id 1 location "Watershed Trailhead" urls ["https://example.com/parking", "https://example.com/map"]
- Give me details for activity 1
- Give me activity details for "Visit Grateful Bread"
- Get daily briefing for 2026-06-10 rain_chance 40 readiness 25
- Log activity id 3 status done notes "30 minute walk"
- Get daily briefing for 2026-06-09

Available MCP tools now include:

- `get_daily_briefing`
- `log_activity`
- `add_appointment`
- `add_timed_event`
- `add_activity`
- `update_activity`
- `get_activity_details`
