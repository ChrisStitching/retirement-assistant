# Retirement Assistant Copilot Instructions

- Domain grounding source of truth: `documentation/design.md` (Conceptual Model section).
- Treat conceptual definitions in `documentation/design.md` as canonical for: daily briefing, activity, readiness, weather sensitivity, category semantics, and recommendation goals.
- Do not invent schema fields, MCP parameters, or business rules that are not documented in `documentation/design.md`, `db/schema.sql`, or implemented MCP tool behavior.
- If behavior or schema changes, update the Conceptual Model in `documentation/design.md` in the same change.

- Prefer the retirement-assistant MCP tools for user-facing data operations before using scripts or direct database access.
- Treat MCP as the default path for daily briefings, appointments, timed events, annual events, activities, and activity logging.
- Keep data operations on MCP tools; use scripts only for setup/maintenance workflows such as `scripts/setup_db.py`.
- If terminal execution is needed, use the repository virtual environment at `.venv/Scripts/python.exe` instead of system Python.
- When extending data workflows, add or update MCP tools first rather than adding new direct-write scripts.
- After changing any MCP tool behavior, run scoped unit tests before finishing to confirm no regressions.
- When adding new MCP tool features or behaviors, add or update unit tests to verify the new behavior.
- After MCP tool changes, review `README.md` and files in `documentation/`, and update them when behavior, usage, or workflows have changed.

## MCP-First Workflow Examples

- Activity field change (new or updated field):
	- Update schema in `db/schema.sql` and any compatibility migration paths in `mcp/server.py` and `scripts/setup_db.py`.
	- Update MCP activity tool paths in `mcp/server.py` (`add_activity`, `update_activity`, and any read/detail/list responses that should expose the field).
	- Add or update tests in `tests/test_activity_crud.py` and related briefing tests if the field affects recommendations.

- Daily briefing logic change:
	- Update date-window SQL selection and Python post-query filter/selection logic in `mcp/server.py` together.
	- Keep behavior aligned with conceptual definitions in `documentation/design.md`.
	- Add or update tests in `tests/test_daily_briefing.py` (and `tests/test_weekday_constraints.py` when weekday behavior is involved).

- New recommendation rule:
	- Write or update a focused test in `tests/test_daily_briefing.py` first to define expected behavior.
	- Implement the rule in `mcp/server.py` without weakening existing filters.
	- Re-run scoped briefing tests and adjust docs if user-visible behavior changed.

- MCP tool behavior or contract change:
	- Update tool implementation and validation in `mcp/server.py`.
	- Add/update unit tests for success and failure paths in the relevant `tests/test_*.py` file.
	- Update usage references in `README.md` and conceptual/behavior notes in `documentation/design.md`.

- Configuration-driven behavior change:
	- Add shared defaults to `settings.example.json` and load/use them in `mcp/server.py`.
	- Keep per-user overrides in `settings.local.json` and avoid hardcoding personal values.
	- Document new keys and defaults in `documentation/design.md`.

- Anti-pattern to avoid:
	- Do not add or rely on direct-write scripts for normal user-facing CRUD or briefing flows when MCP tools can be extended.

## Do Not Rules

- Do not write directly to the runtime SQLite database for user-facing CRUD or briefing behavior.
	- Allowed exceptions: unit tests, setup/migration scripts, and maintenance scripts.
	- Preferred path: implement runtime behavior in MCP tools in `mcp/server.py`.

- Do not bypass MCP tools for normal CRUD operations.
	- Preferred path: extend or update the existing MCP tool surface first.

- Never write personal or machine-specific values into `settings.example.json`.
	- Use `settings.local.json` for all local overrides.
	- Preferred path: keep shared defaults in `settings.example.json` and user-specific values only in `settings.local.json`.

- Do not add new scripts for runtime behavior.
	- Preferred path: keep `scripts/` focused on setup and maintenance workflows.

- Do not introduce external dependencies without updating `requirements.txt`.
	- Preferred path: add/update dependency pins and ensure related docs/tests reflect the change.

- Do not change schema without updating compatibility migration paths.
	- Preferred path: update `db/schema.sql`, migration handling in `scripts/setup_db.py`, and runtime compatibility handling in `mcp/server.py` together.