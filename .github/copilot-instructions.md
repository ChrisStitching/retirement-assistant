# Retirement Assistant Copilot Instructions

- Prefer the retirement-assistant MCP tools for user-facing data operations before using scripts or direct database access.
- Treat MCP as the default path for daily briefings, appointments, timed events, annual events, activities, and activity logging.
- Keep data operations on MCP tools; use scripts only for setup/maintenance workflows such as `scripts/setup_db.py`.
- If terminal execution is needed, use the repository virtual environment at `.venv/Scripts/python.exe` instead of system Python.
- When extending data workflows, add or update MCP tools first rather than adding new direct-write scripts.
- After changing any MCP tool behavior, run scoped unit tests before finishing to confirm no regressions.
- When adding new MCP tool features or behaviors, add or update unit tests to verify the new behavior.
- After MCP tool changes, review `README.md` and files in `documentation/`, and update them when behavior, usage, or workflows have changed.