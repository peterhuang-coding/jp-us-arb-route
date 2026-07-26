"""CLI smoke tests — invoke the CLI as a subprocess to catch regressions."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    """Isolated DB so tests don't write to the real db.sqlite.

    Seeds in-process AND sets ``ARB_DB_PATH`` env var so subprocess CLI
    calls inherit the tmp path via ``arb.db.connect``.
    """
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    monkeypatch.setenv("ARB_DB_PATH", str(db_file))
    import arb.db as arb_db   # imported after monkeypatch
    import arb.seed as arb_seed
    conn = arb_db.connect(db_file)
    try:
        arb_seed.seed_all(conn)
    finally:
        conn.close()
    yield db_file


def _run(*args, env=None):
    """Run the CLI as a subprocess with the scratch ARB_DB_PATH set.

    Pass ``env=str(db_file)`` to override; otherwise inherits from
    ``scratch_db``'s monkeypatched env.
    """
    full_env = os.environ.copy()
    if env is not None:
        full_env["ARB_DB_PATH"] = str(env)
    return subprocess.run(
        [sys.executable, "-m", "arb", *args],
        cwd=ROOT, capture_output=True, text=True, env=full_env,
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
    # Round 5: scenarios now part of decide output.
    assert "三档情景" in out.stdout
    assert "保守" in out.stdout and "中性" in out.stdout and "乐观" in out.stdout


def test_decide_rejects_invalid_inputs(scratch_db):
    out = _run("decide", "--sku", "JP-LUX-PATEK", "--units", "0")
    assert out.returncode != 0
    assert "error" in out.stderr.lower()


def test_scenarios_cli_text(scratch_db):
    out = _run("scenarios", "--sku", "JP-SKII-FT230", "--units", "5")
    assert out.returncode == 0
    assert "决策" in out.stdout
    assert "三档情景" in out.stdout
    assert "保守" in out.stdout and "中性" in out.stdout and "乐观" in out.stdout


def test_scenarios_cli_json(scratch_db):
    out = _run("scenarios", "--sku", "JP-SKII-FT230", "--units", "5", "--json")
    assert out.returncode == 0
    payload = json.loads(out.stdout)
    assert payload["sku"] == "JP-SKII-FT230"
    assert len(payload["scenarios"]) == 3
    names = [s["name"] for s in payload["scenarios"]]
    assert names == ["保守", "中性", "乐观"]


def test_scenarios_cli_unknown_sku(scratch_db):
    out = _run("scenarios", "--sku", "DOES-NOT-EXIST", "--units", "1")
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
    # scratch_db seeds only the 6 whitelist SKUs (seed_all() inserts via
    # upsert, so any pre-existing rows in the tmp DB are clobbered, but the
    # tmp DB starts empty — see scratch_db fixture).
    assert "opportunities: 6" in out.stdout
    assert "routes: 1" in out.stdout


def test_report_writes_html(scratch_db, tmp_path):
    out = _run("report", "--sku", "JP-SKII-FT230", "--units", "5",
               "--html", "--out", str(tmp_path))
    assert out.returncode == 0, out.stderr
    written = list(tmp_path.glob("*.html"))
    assert written, f"no html file in {tmp_path} (stdout: {out.stdout!r})"
    body = written[0].read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in body
    assert "决策报告" in body
    assert "JP-SKII-FT230" in body


def test_report_writes_pdf(scratch_db, tmp_path):
    out = _run("report", "--sku", "JP-NINTENDO-SWOLED", "--units", "10",
               "--pdf", "--out", str(tmp_path))
    assert out.returncode == 0, out.stderr
    written = list(tmp_path.glob("*.pdf"))
    assert written, f"no pdf file in {tmp_path} (stdout: {out.stdout!r})"
    head = written[0].read_bytes()[:4]
    assert head == b"%PDF", f"bad PDF magic: {head!r}"


def test_report_default_is_markdown(scratch_db, tmp_path):
    out = _run("report", "--sku", "JP-DYSON-V12S", "--units", "3",
               "--out", str(tmp_path / "r.md"))
    assert out.returncode == 0
    body = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert body.startswith("# 决策报告")


def test_report_unknown_sku_exits_nonzero(scratch_db):
    out = _run("report", "--sku", "NOPE", "--units", "1")
    assert out.returncode != 0
    assert "error" in out.stderr.lower() or "not found" in out.stderr.lower()


def test_serve_help_does_not_boot_server(scratch_db):
    """`serve --help` must not actually start uvicorn."""
    out = _run("serve", "--help")
    assert out.returncode == 0
    assert "--host" in out.stdout
    assert "--port" in out.stdout


def test_freshness_lists_all_opps_with_status(scratch_db):
    """`freshness` (no SKU) must show a verdict line per opp."""
    out = _run("freshness")
    assert out.returncode == 0
    # seed ts is 2026-07-01; today is 2026-07-26 → every row is "aging" (25 days)
    assert "aging" in out.stdout
    assert "临近复核" in out.stdout
    for sku in ("JP-SKII-FT230", "JP-WS-YAMAZAKI12"):
        assert sku in out.stdout


def test_freshness_filters_to_one_sku(scratch_db):
    out = _run("freshness", "--sku", "JP-SKII-FT230")
    assert out.returncode == 0
    assert "JP-SKII-FT230" in out.stdout
    # should not include unrelated SKUs
    assert "JP-WS-YAMAZAKI12" not in out.stdout


def test_freshness_unknown_sku_errors(scratch_db):
    out = _run("freshness", "--sku", "NOPE")
    assert out.returncode != 0
    assert "unknown sku" in out.stderr.lower()


# ---------- Round 4: verify + proposals ----------

def test_verify_unknown_sku_exits_nonzero(scratch_db):
    out = _run("verify", "--sku", "NOPE")
    assert out.returncode != 0
    payload = json.loads(out.stdout)
    assert payload["sku"] == "NOPE"
    assert payload["verified_now"] is False
    assert payload["message"].startswith("opportunity not found")


def test_verify_help_runs(scratch_db):
    out = _run("verify", "--help")
    assert out.returncode == 0
    assert "--tolerance" in out.stdout
    assert "--dry-run" in out.stdout


def test_proposals_help_runs(scratch_db):
    out = _run("proposals", "--help")
    assert out.returncode == 0
    assert "apply" in out.stdout
    assert "reject" in out.stdout


def test_proposals_list_empty_when_none_pending(scratch_db):
    """Fresh tmp DB → 0 rows in proposed_prices."""
    out = _run("proposals")
    assert out.returncode == 0
    assert "no proposals" in out.stdout


def test_proposals_filter_by_status(scratch_db):
    out = _run("proposals", "--status", "applied")
    assert out.returncode == 0


def test_proposals_apply_invalid_id_exits_nonzero(scratch_db):
    out = _run("proposals", "apply", "99999")
    assert out.returncode != 0
    payload = json.loads(out.stdout)
    assert payload["applied"] is False
    assert "not found" in payload["message"]
