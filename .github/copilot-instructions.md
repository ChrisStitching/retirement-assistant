# Retirement Assistant Copilot Instructions

- Prefer the retirement-assistant MCP tools for user-facing data operations before using scripts or direct database access.
- Treat MCP as the default path for daily briefings, appointments, timed events, annual events, activities, and activity logging.
- Use scripts only when no MCP tool exists yet or when explicitly asked for CLI usage.
- If terminal execution is needed, use the repository virtual environment at `.venv/Scripts/python.exe` instead of system Python.
- When extending data workflows, add or update MCP tools first, then keep scripts as secondary fallbacks only when still useful.