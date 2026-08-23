"""M0 CLI smoke tests — 子进程跑 `arb execution`."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run(*args, env=None):
    full_env = os.environ.copy()
    if env is not None:
        full_env["ARB_DB_PATH"] = str(env)
    return subprocess.run(
        [sys.executable, "-m", "arb", *args],
        cwd=ROOT, capture_output=True, text=True, env=full_env,
    )


def test_execution_demo_runs_full_chain_in_memory():
    out = _run("execution", "demo")
    assert out.returncode == 0, out.stderr
    assert "completed" in out.stdout
    assert "awaiting_flight" in out.stdout
    assert "order #1" in out.stdout and "order #2" in out.stdout


@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setenv("ARB_DB_PATH", str(db_file))
    import arb.db as arb_db
    import arb.seed as arb_seed
    conn = arb_db.connect(db_file)
    try:
        arb_seed.seed_all(conn)
    finally:
        conn.close()
    yield db_file


def test_execution_list_json(scratch_db):
    out = _run("execution", "list", "--json", env=scratch_db)
    assert out.returncode == 0
    data = json.loads(out.stdout)
    assert isinstance(data, list)
