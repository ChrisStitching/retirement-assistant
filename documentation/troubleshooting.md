# Retirement Assistant Troubleshooting Guide

## Who This Is For

This guide is for anyone running the project on a new machine and trying to diagnose setup, configuration, or runtime issues.

## Quick Checks

Run these checks first in the project root:

```powershell
# 1) Confirm virtual environment Python exists
.\.venv\Scripts\python.exe --version

# 2) Confirm dependencies are installed
.\.venv\Scripts\python.exe -m pip show mcp certifi

# 3) Confirm local settings file exists
Test-Path .\settings.local.json

# 4) Initialize DB schema if needed
.\.venv\Scripts\python.exe scripts\setup_db.py
```

## Common Issues And Fixes

### 1. MCP tools are not available in Copilot

Symptoms:
- Tool calls fail or do not appear.
- Copilot does not seem connected to the local server.

Checks:
- Verify [.vscode/mcp.json](../.vscode/mcp.json) exists and points to the project virtual environment Python.
- Verify `cwd` is the workspace root.

Fixes:
- Reopen the workspace in VS Code.
- Restart the MCP server process.
- Confirm `.venv` exists and dependencies are installed.

### 2. Import errors, especially mcp or certifi

Symptoms:
- `ModuleNotFoundError: No module named mcp`
- `ModuleNotFoundError: No module named certifi`

Fix:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then restart the MCP server.

### 3. Database errors such as no such table

Symptoms:
- Errors like `sqlite3.OperationalError: no such table: activities`

Cause:
- Database was not initialized yet, or `db_path` points to a fresh file.

Fix:

```powershell
.\.venv\Scripts\python.exe scripts\setup_db.py
```

Then verify `db_path` in [settings.local.json](../settings.local.json).

### 4. Daily briefing works but weather is always null

Symptoms:
- `weather: null`
- `rain_chance: null` when not passed manually

Checks:
- Confirm `weather.enabled` is `true` in [settings.local.json](../settings.local.json).
- Confirm latitude, longitude, and timezone are present.

Example:

```json
"weather": {
  "enabled": true,
  "latitude": 47.4502,
  "longitude": -122.3088,
  "timezone": "America/Los_Angeles"
}
```

Fixes:
- Correct weather settings and restart the MCP server.
- Verify outbound HTTPS is allowed on your network.

### 5. SSL certificate verify failed during weather lookup

Symptoms:
- Warning similar to: `CERTIFICATE_VERIFY_FAILED`

Cause:
- Local certificate trust chain is not available to Python.

Fixes:
- Ensure `certifi` is installed from requirements.
- Restart server after dependency install.
- If corporate network interception is in place, test from a non-intercepted network.

### 6. Changes to code or settings do not take effect

Symptoms:
- Behavior still reflects older logic after edits.

Cause:
- MCP server process is still running old code/settings.

Fix:
- Fully stop and restart the MCP server process.

### 7. Wrong file path or accidental path leakage

Symptoms:
- Config works only on one machine.
- Shared repo includes personal absolute paths.

Fixes:
- Keep personal paths only in [settings.local.json](../settings.local.json).
- Keep reusable defaults in [settings.example.json](../settings.example.json).
- Do not commit machine-specific paths.

## Verification Checklist

After setup, verify all of the following:
- MCP server starts without traceback.
- `get_daily_briefing` returns appointments/events and activity suggestions.
- Weather object appears when weather is enabled.
- Recently completed activities are excluded according to `briefing_lookback_days`.
- Recommendation filters behave as expected for readiness and temperature.

## Support Data To Collect When Debugging

When reporting an issue, include:
- OS and Python version.
- Exact command used to start the server.
- Relevant terminal error output.
- Current [settings.local.json](../settings.local.json) values with personal paths redacted if needed.
- Whether a server restart was performed after changes.
