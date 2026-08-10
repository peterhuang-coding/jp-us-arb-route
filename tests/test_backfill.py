"""Tests for ``arb backfill-home-prices`` (Round 15).

Covers payload coercion, per-row validation, dry-run semantics, and the
``--file`` / stdin paths.  All tests use isolated DBs so the real
``data/db.sqlite`` is never touched.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
from arb.cli import _coerce_backfill_rows, _validate_backfill_row, cmd_backfill_home_prices
from arb.db import connect, get_opportunity


# ---------- payload coercion ----------

class TestCoerceBackfillRows:
    def test_list_passthrough(self):
        rows = [{"sku": "A", "home_price_cny": 100}]
        assert _coerce_backfill_rows(rows) == rows

    def test_single_dict_shorthand(self):
        rows = _coerce_backfill_rows({"sku": "A", "home_price_cny": 100})
        assert rows == [{"sku": "A", "home_price_cny": 100}]

    def test_empty_list_returns_empty(self):
        assert _coerce_backfill_rows([]) == []

    def test_non_list_non_dict_raises(self):
        with pytest.raises(ValueError, match="payload must be a list or dict"):
            _coerce_backfill_rows("not json")

    def test_row_must_be_dict(self):
        with pytest.raises(ValueError, match="row #0 must be a dict"):
            _coerce_backfill_rows(["not-a-dict"])

    def test_row_missing_sku_raises(self):
        with pytest.raises(ValueError, match="missing required key"):
            _coerce_backfill_rows([{"home_price_cny": 100}])

    def test_row_missing_home_price_raises(self):
        with pytest.raises(ValueError, match="missing required key"):
            _coerce_backfill_rows([{"sku": "A"}])

    def test_row_blank_sku_raises(self):
        with pytest.raises(ValueError, match="non-empty string"):
            _coerce_backfill_rows([{"sku": "   ", "home_price_cny": 100}])

    def test_row_shallow_copied(self):
        original = {"sku": "A", "home_price_cny": 100}
        result = _coerce_backfill_rows([original])
        result[0]["home_price_cny"] = 200
        assert original["home_price_cny"] == 100


# ---------- per-row validation ----------

class TestValidateBackfillRow:
    def test_valid(self):
        assert _validate_backfill_row({"sku": "A", "home_price_cny": 1500}) is None

    def test_zero_price_allowed(self):
        # ¥0 = explicit "no China reference" marker; basket will skip with reason
        assert _validate_backfill_row({"sku": "A", "home_price_cny": 0}) is None

    def test_price_negative_rejected(self):
        reason = _validate_backfill_row({"sku": "A", "home_price_cny": -1})
        assert "out of bounds" in reason

    def test_price_too_high_rejected(self):
        reason = _validate_backfill_row({"sku": "A", "home_price_cny": 100001})
        assert "out of bounds" in reason

    def test_price_at_upper_bound_accepted(self):
        assert _validate_backfill_row({"sku": "A", "home_price_cny": 100000}) is None

    def test_price_non_numeric_rejected(self):
        reason = _validate_backfill_row({"sku": "A", "home_price_cny": "1500"})
        assert "must be a number" in reason

    def test_blank_sku_rejected(self):
        reason = _validate_backfill_row({"sku": "", "home_price_cny": 100})
        assert "non-empty string" in reason

    def test_max_units_zero_rejected(self):
        reason = _validate_backfill_row({"sku": "A", "home_price_cny": 100, "max_units_per_trip": 0})
        assert "max_units_per_trip" in reason

    def test_max_units_string_rejected(self):
        reason = _validate_backfill_row({"sku": "A", "home_price_cny": 100, "max_units_per_trip": "5"})
        assert "max_units_per_trip" in reason

    def test_max_units_valid(self):
        assert _validate_backfill_row({"sku": "A", "home_price_cny": 100, "max_units_per_trip": 5}) is None


# ---------- in-process cmd tests (--file path) ----------

@pytest.fixture
def seeded_conn(tmp_path, monkeypatch):
    """In-process seed of an isolated DB."""
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    monkeypatch.setenv("ARB_DB_PATH", str(db_file))
    import arb.seed as arb_seed
    conn = connect(db_file)
    arb_seed.seed_all(conn)
    return conn


def _ns(*, dry_run: bool, json_out: bool, file: Path | None):
    ns = argparse.Namespace()
    ns.dry_run = dry_run
    ns.json = json_out
    ns.file = file
    return ns


class TestCmdBackfillHomePrices:
    # Seeded values (see arb/seed.py)
    SKII_SEED_PRICE = 1100.0
    SKII_SEED_MAX = 6
    NEW_PRICE = 1350.0

    def test_dry_run_does_not_persist(self, seeded_conn, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": self.NEW_PRICE}]))
        cmd_backfill_home_prices(_ns(dry_run=True, json_out=False, file=f))
        assert get_opportunity(seeded_conn, "JP-SKII-FT230")["home_price_cny"] == self.SKII_SEED_PRICE

    def test_persists_when_not_dry_run(self, seeded_conn, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": self.NEW_PRICE}]))
        cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        assert get_opportunity(seeded_conn, "JP-SKII-FT230")["home_price_cny"] == self.NEW_PRICE

    def test_bumps_data_freshness_ts(self, seeded_conn, tmp_path):
        before = get_opportunity(seeded_conn, "JP-SKII-FT230")["data_freshness_ts"]
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": self.NEW_PRICE}]))
        cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        after = get_opportunity(seeded_conn, "JP-SKII-FT230")["data_freshness_ts"]
        assert after != before

    def test_unknown_sku_skipped(self, seeded_conn, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-DOES-NOT-EXIST", "home_price_cny": 100}]))
        rc = cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        out = capsys.readouterr().out
        assert "sku not found in DB" in out
        assert rc == 1  # write mode + all skipped → non-zero

    def test_unknown_sku_dry_run_returns_zero(self, seeded_conn, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-DOES-NOT-EXIST", "home_price_cny": 100}]))
        rc = cmd_backfill_home_prices(_ns(dry_run=True, json_out=False, file=f))
        assert rc == 0  # dry-run never errors

    def test_invalid_price_skipped(self, seeded_conn, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": 999999}]))
        rc = cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        out = capsys.readouterr().out
        assert "out of bounds" in out
        # Value unchanged from seed
        assert get_opportunity(seeded_conn, "JP-SKII-FT230")["home_price_cny"] == self.SKII_SEED_PRICE
        assert rc == 1

    def test_mixed_valid_and_invalid(self, seeded_conn, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([
            {"sku": "JP-SKII-FT230", "home_price_cny": self.NEW_PRICE},     # valid
            {"sku": "JP-WS-YAMAZAKI12", "home_price_cny": -50},            # invalid
            {"sku": "JP-NINTENDO-SWOLED", "home_price_cny": self.NEW_PRICE + 100},  # valid
        ]))
        cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        assert get_opportunity(seeded_conn, "JP-SKII-FT230")["home_price_cny"] == self.NEW_PRICE
        assert get_opportunity(seeded_conn, "JP-NINTENDO-SWOLED")["home_price_cny"] == self.NEW_PRICE + 100
        # Invalid row: seed value untouched (seed has 1800 for whisky)
        assert get_opportunity(seeded_conn, "JP-WS-YAMAZAKI12")["home_price_cny"] == 1800.0

    def test_max_units_per_trip_optional_update(self, seeded_conn, tmp_path):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": self.NEW_PRICE,
                                   "max_units_per_trip": 3}]))
        cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        row = get_opportunity(seeded_conn, "JP-SKII-FT230")
        assert row["home_price_cny"] == self.NEW_PRICE
        assert row["max_units_per_trip"] == 3

    def test_max_units_omitted_preserved(self, seeded_conn, tmp_path):
        before = get_opportunity(seeded_conn, "JP-SKII-FT230")["max_units_per_trip"]
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": self.NEW_PRICE}]))
        cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        assert get_opportunity(seeded_conn, "JP-SKII-FT230")["max_units_per_trip"] == before

    def test_empty_file_is_noop(self, seeded_conn, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text("[]")
        rc = cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        assert rc == 0
        assert "0 updated" in capsys.readouterr().out

    def test_json_payload_shape_error(self, seeded_conn, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text("not json at all")
        rc = cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        assert rc == 2
        assert "error:" in capsys.readouterr().err

    def test_single_dict_shorthand(self, seeded_conn, tmp_path):
        # Single object (not array) is accepted as shorthand for one row.
        f = tmp_path / "in.json"
        f.write_text(json.dumps({"sku": "JP-SKII-FT230", "home_price_cny": self.NEW_PRICE}))
        cmd_backfill_home_prices(_ns(dry_run=False, json_out=False, file=f))
        assert get_opportunity(seeded_conn, "JP-SKII-FT230")["home_price_cny"] == self.NEW_PRICE

    def test_json_out_mode(self, seeded_conn, tmp_path, capsys):
        f = tmp_path / "in.json"
        f.write_text(json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": self.NEW_PRICE}]))
        cmd_backfill_home_prices(_ns(dry_run=False, json_out=True, file=f))
        out = capsys.readouterr().out
        report = json.loads(out)
        assert report["updated"][0]["sku"] == "JP-SKII-FT230"
        assert report["updated"][0]["old_home_price_cny"] == self.SKII_SEED_PRICE
        assert report["updated"][0]["new_home_price_cny"] == self.NEW_PRICE
        assert report["dry_run"] is False


# ---------- subprocess smoke (stdin path) ----------

@pytest.fixture
def seeded_subprocess_db(tmp_path, monkeypatch):
    """Seed an isolated DB and expose the path for subprocess CLI runs."""
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    monkeypatch.setenv("ARB_DB_PATH", str(db_file))
    import arb.seed as arb_seed
    conn = connect(db_file)
    arb_seed.seed_all(conn)
    conn.close()
    return db_file


def _run_cli(*args, stdin_payload: str | None = None):
    """Run the CLI as subprocess; capture stdout/stderr."""
    return subprocess.run(
        [sys.executable, "-m", "arb", *args],
        cwd=ROOT, capture_output=True, text=True,
        input=stdin_payload,
    )


class TestStdinPath:
    def test_stdin_writes_successfully(self, seeded_subprocess_db, tmp_path, monkeypatch):
        monkeypatch.setenv("ARB_DB_PATH", str(seeded_subprocess_db))
        payload = json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": 1350}])
        r = _run_cli("backfill-home-prices", stdin_payload=payload)
        assert r.returncode == 0
        conn = connect(seeded_subprocess_db)
        try:
            assert get_opportunity(conn, "JP-SKII-FT230")["home_price_cny"] == 1350.0
        finally:
            conn.close()

    def test_stdin_dry_run_does_not_write(self, seeded_subprocess_db, monkeypatch):
        monkeypatch.setenv("ARB_DB_PATH", str(seeded_subprocess_db))
        payload = json.dumps([{"sku": "JP-SKII-FT230", "home_price_cny": 1350}])
        r = _run_cli("backfill-home-prices", "--dry-run", stdin_payload=payload)
        assert r.returncode == 0
        conn = connect(seeded_subprocess_db)
        try:
            # Seed price 1100 unchanged
            assert get_opportunity(conn, "JP-SKII-FT230")["home_price_cny"] == 1100.0
        finally:
            conn.close()