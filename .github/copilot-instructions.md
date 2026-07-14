# Retirement Assistant Copilot Instructions

## Domain Grounding

- Domain grounding source of truth: `documentation/design.md` (Conceptual Model section).
- Treat conceptual definitions in `documentation/design.md` as canonical for: daily briefing, activity, readiness, weather sensitivity, category semantics, and activity suggestion goals.
- Do not invent schema fields, MCP parameters, or business rules that are not documented in `documentation/design.md`, `db/schema.sql`, or implemented MCP tool behavior.
- If behavior or schema changes, update the Conceptual Model in `documentation/design.md` in the same change.

## Copilot's Role

- Copilot serves two roles in this project:
	- Developer assistant: updates code, tests, schema, and documentation.
	- Runtime assistant: performs user-facing operations through MCP tools.
- Use pragmatic separation: both roles may appear in one task, but actions must stay explicit and not be conflated.
- If the request is a user-facing data operation, use MCP tools first.
- If the request changes runtime behavior, implement in MCP/server code and add or update tests before considering the change complete.
- Do not create new runtime workflows outside MCP unless explicitly requested as a design change.

## Operating Defaults

- Prefer the retirement-assistant MCP tools for user-facing data operations; use scripts only for setup and maintenance workflows.
- If terminal execution is needed, use the repository virtual environment at `.venv/Scripts/python.exe` instead of system Python.
- After changing any MCP tool behavior, run scoped unit tests before finishing and add or update coverage for new behavior.
- After MCP tool changes, review `README.md` and files in `documentation/`, and update them when behavior, usage, or workflows have changed.

## Where Logic Lives

- `db/schema.sql`: database structure and schema evolution source of truth.
- `mcp/server.py`: MCP tool contracts, input validation, and runtime activity suggestion/briefing logic.
- `tests/`: behavioral guarantees and regression protection for MCP behavior.
- `documentation/` and `README.md`: design intent, conceptual model, and user-facing usage guidance.
- `scripts/`: setup, migration, and maintenance workflows only.
- Guardrail: if a change affects runtime user-facing behavior, implement it in MCP tools and tests, not in scripts.

## Schema Change Protocol

When changing schema, complete all steps in this sequence within the same change:

1. Update schema source of truth in `db/schema.sql`.
2. Update compatibility migration handling in both `scripts/setup_db.py` and `mcp/server.py`.
3. Update MCP SQL queries, validation, and response payload mappings in `mcp/server.py`.
4. Add or update unit tests in `tests/` for success, failure, and compatibility paths.
5. Update conceptual and behavior documentation in `documentation/design.md`.
6. Update user-facing usage notes in `README.md`.

Completion rule:
- A schema change is incomplete unless schema, migration paths, MCP behavior, tests, and docs are all updated together.

## MCP-First Workflow Examples

- Activity field change (new or updated field):
	- Update schema in `db/schema.sql` and compatibility migrations in `mcp/server.py` and `scripts/setup_db.py`.
	- Update activity MCP paths in `mcp/server.py` (`add_activity`, `update_activity`, and any read/detail/list responses that expose the field).
	- Add or update tests in `tests/test_activity_crud.py` and briefing tests if the field affects activity suggestions.

- Daily briefing logic change:
	- Update date-window SQL selection and Python filter/selection logic in `mcp/server.py` together.
	- Keep behavior aligned with conceptual definitions in `documentation/design.md`.
	- Add or update tests in `tests/test_daily_briefing.py` (and `tests/test_weekday_constraints.py` when weekday behavior is involved).

- New activity suggestion rule:
	- Write or update a focused test in `tests/test_daily_briefing.py` first to define expected behavior.
	- Implement the rule in `mcp/server.py` without weakening existing filters.
	- Re-run scoped briefing tests and adjust docs if user-visible behavior changed.

- MCP tool behavior or contract change:
	- Update tool implementation and validation in `mcp/server.py`.
	- Add or update success and failure path tests in the relevant `tests/test_*.py` file.
	- Update usage references in `README.md` and conceptual/behavior notes in `documentation/design.md`.

- Configuration-driven behavior change:
	- Add shared defaults to `settings.example.json` and load/use them in `mcp/server.py`.
	- Keep per-user overrides in `settings.local.json` and avoid hardcoding personal values.
	- Document new keys and defaults in `documentation/design.md`.

- Anti-pattern to avoid:
	- Do not add or rely on direct-write scripts for normal user-facing CRUD or briefing flows when MCP tools can be extended.

## Testing Expectations

- New MCP tool:
	- Add success and failure path tests in the relevant `tests/test_*.py` file.
	- If the tool supports create/update/delete behavior, include CRUD-oriented coverage.

- New activity field:
	- Add add, update, and detail/read tests in `tests/test_activity_crud.py`.
	- Add or update briefing tests when the field affects activity suggestion filtering or selection.

- New activity suggestion rule:
	- Add focused rule tests in `tests/test_daily_briefing.py` before implementation.
	- Verify new rule behavior without weakening existing activity suggestion constraints.

- New filtering rule:
	- Add exclusion tests for records that should be filtered out.
	- Add inclusion tests for records that should remain eligible.

- New configuration behavior:
	- Add tests for default/fallback behavior when config is absent or incomplete.
	- Add tests for override behavior when config values are provided.

- Test quality expectations:
	- Keep tests deterministic and fixture-based.
	- Do not depend on personal runtime SQLite data.

- Scoped and full test commands:
	- `./.venv/Scripts/python.exe -m pytest tests/test_activity_crud.py`
	- `./.venv/Scripts/python.exe -m pytest tests/test_appointment_crud.py`
	- `./.venv/Scripts/python.exe -m pytest tests/test_timed_event_crud.py`
	- `./.venv/Scripts/python.exe -m pytest tests/test_daily_briefing.py tests/test_weekday_constraints.py`
	- `./.venv/Scripts/python.exe -m pytest`

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
	- Preferred path: update dependency pins and related docs/tests in the same change.

- Do not change schema without following the Schema Change Protocol.
	- Preferred path: update schema, migrations, MCP behavior, tests, and docs together in one change.