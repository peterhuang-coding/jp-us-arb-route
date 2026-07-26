"""CLI smoke tests — invoke the CLI as a subprocess to catch regressions."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    """Isolated DB so tests don't write to the real db.sqlite."""
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    # Run seed
    subprocess.check_call([sys.executable, "-m", "arb", "seed"],
                          cwd=ROOT, stdout=subprocess.DEVNULL)
    yield db_file


def _run(*args):
    return subprocess.run(
        [sys.executable, "-m", "arb", *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_list_prints_six_opportunities(scratch_db):
    out = _run("list")
    assert out.returncode == 0
    # Should list 6 SKUs
    for sku in (
        "JP-SKII-FT230", "JP-WS-YAMAZAKI12", "JP-NINTENDO-SWOLED",
        "JP-DYSON-V12S", "JP-LUX-PATEK", "JP-ANIME-GK2024",
    ):
        assert sku in out.stdout


def test_decide_returns_decision(scratch_db):
    out = _run("decide", "--sku", "JP-LUX-PATEK", "--units", "3")
    assert out.returncode == 0
    assert "决策" in out.stdout
    assert "建议" in out.stdout or "谨慎" in out.stdout or "不建议" in out.stdout


def test_decide_rejects_invalid_inputs(scratch_db):
    out = _run("decide", "--sku", "JP-LUX-PATEK", "--units", "0")
    assert out.returncode != 0
    assert "error" in out.stderr.lower()


def test_report_writes_markdown(scratch_db, tmp_path):
    out_path = tmp_path / "report.md"
    out = _run("report", "--sku", "JP-NINTENDO-SWOLED", "--units", "10",
               "--out", str(out_path))
    assert out.returncode == 0
    assert out_path.exists()
    body = out_path.read_text(encoding="utf-8")
    assert "# 决策报告" in body
    assert "JP-NINTENDO-SWOLED" in body
    assert "## 数据来源" in body
    assert "## 单件成本明细" in body
    assert "## 综合决策" in body


def test_health(scratch_db):
    out = _run("health")
    assert out.returncode == 0
    assert "opportunities: 6" in out.stdout
    assert "routes: 1" in out.stdout
