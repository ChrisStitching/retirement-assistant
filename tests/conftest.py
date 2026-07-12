from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture()
def server_module():
    server_path = Path(__file__).resolve().parents[1] / "mcp" / "server.py"
    spec = importlib.util.spec_from_file_location("retirement_assistant_server", server_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load server module from {server_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def isolated_server(server_module, tmp_path, monkeypatch):
    db_path = tmp_path / "retirement_assistant_test.db"
    schema_path = Path(__file__).resolve().parents[1] / "db" / "schema.sql"

    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        conn.commit()

    monkeypatch.setattr(server_module, "_db_path", lambda: db_path)
    monkeypatch.setattr(
        server_module,
        "_load_settings",
        lambda: {
            "activity_suggestions_per_day": 3,
            "briefing_lookback_days": 7,
            "weather": {"enabled": False},
        },
    )
    monkeypatch.setattr(server_module, "_fetch_weather_for_date", lambda _target_date: None)

    return server_module, db_path
