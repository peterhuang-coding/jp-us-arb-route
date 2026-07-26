"""Round-13 regression — `db.add_proposed_price` + `db.resolve_proposed_price(apply)`
must persist the proposed value into the parent opportunity row.

Round-6 commit ``563aa34`` shipped ``scripts/apply_research_proposals.py`` to
stage and apply 11 calibration proposals.  Subsequent round-12 review
discovered that every applied proposal left the corresponding
``opportunities.{purchase,sell}_price_usd`` row untouched at its seed value
(proposed_prices had ``status='applied'`` but the parent never moved), so
``arb list`` and ``arb decide`` both returned stale pre-research numbers.

The bug was masked because each individual helper (`add_proposed_price`,
`resolve_proposed_price`) returned sensible dicts — the round-7 tests in
``test_proposal_resolution.py`` exercised them in isolation and passed.  The
gap was the **integration** path: ``add`` then ``resolve_proposed_price`` on
the same connection must be observable in a follow-up ``get_opportunity``
read.  These four cases pin that contract.

The bug was almost certainly caused by a post-round-7 ``arb seed`` /
``seed_all()`` call that re-upserted the 6 whitelist SKUs with their
seed values (clobbering the round-6 calibrated prices) while leaving the
``proposed_prices`` table in its ``applied`` state.  Either way, the
contract under test here is independent of the reseed and pins the
behavior the production fix now relies on.
"""
from __future__ import annotations

import pytest

import arb.db as arb_db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Per-test DB seeded with the 6 whitelist SKUs + 2 routes."""
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    monkeypatch.setenv("ARB_DB_PATH", str(db_file))
    conn = arb_db.connect(db_file)
    from arb.seed import seed_all
    seed_all(conn)
    conn.close()
    return db_file


def test_add_then_apply_persists_purchase_price(fresh_db):
    """Stage a buy-price proposal, apply it, then re-read: the parent's
    purchase_price_usd must equal the proposed value (not the seed value)."""
    conn = arb_db.connect(fresh_db)
    try:
        before = arb_db.get_opportunity(conn, "JP-SKII-FT230")
        original_buy = float(before["purchase_price_usd"])
        original_ts = before["data_freshness_ts"]

        pid = arb_db.add_proposed_price(
            conn, before["id"], "purchase_price_usd",
            stored_value=original_buy,
            proposed_value=150.0,
            detected_currency="USD",
            detected_raw="$150.00 (round-13 regression fixture)",
            source_url="https://example.invalid/round-13-fixture",
            drift_pct=abs(150.0 - original_buy) / original_buy * 100.0,
        )
        result = arb_db.resolve_proposed_price(conn, pid, "apply")
        assert result["applied"] is True
        assert result["proposal_status"] == "applied"
        assert result["new_value"] == pytest.approx(150.0)

        after = arb_db.get_opportunity(conn, "JP-SKII-FT230")
        assert float(after["purchase_price_usd"]) == pytest.approx(150.0), (
            "parent purchase_price_usd must equal the proposed value after apply()"
        )
        # data_freshness_ts must move on apply; the round-13 fix uses today=2026-07-26
        assert after["data_freshness_ts"] != original_ts
    finally:
        conn.close()


def test_add_then_apply_persists_sell_price(fresh_db):
    """Symmetric to the buy-price case for sell_price_usd — the round-6
    calibration applied sell-price changes for every SKU and the regression
    must hold for that column too."""
    conn = arb_db.connect(fresh_db)
    try:
        before = arb_db.get_opportunity(conn, "JP-LUX-PATEK")
        original_sell = float(before["sell_price_usd"])

        pid = arb_db.add_proposed_price(
            conn, before["id"], "sell_price_usd",
            stored_value=original_sell,
            proposed_value=7800.0,
            detected_currency="USD",
            detected_raw="$7800.00 (round-13 regression fixture)",
            source_url="https://example.invalid/round-13-fixture",
            drift_pct=abs(7800.0 - original_sell) / original_sell * 100.0,
        )
        result = arb_db.resolve_proposed_price(conn, pid, "apply")
        assert result["applied"] is True

        after = arb_db.get_opportunity(conn, "JP-LUX-PATEK")
        assert float(after["sell_price_usd"]) == pytest.approx(7800.0), (
            "parent sell_price_usd must equal the proposed value after apply()"
        )
    finally:
        conn.close()


def test_apply_persists_both_fields_in_sequence(fresh_db):
    """Stage + apply *both* purchase and sell for one SKU on the same
    connection — mirrors the per-SKU two-proposal pattern from
    scripts/apply_research_proposals.py for SKII / Nintendo / Dyson / Patek /
    Anime-GK2024."""
    conn = arb_db.connect(fresh_db)
    try:
        before = arb_db.get_opportunity(conn, "JP-NINTENDO-SWOLED")
        original_buy = float(before["purchase_price_usd"])
        original_sell = float(before["sell_price_usd"])

        buy_pid = arb_db.add_proposed_price(
            conn, before["id"], "purchase_price_usd",
            stored_value=original_buy, proposed_value=319.87,
            detected_currency="USD", detected_raw="$319.87",
            source_url="https://example.invalid/round-13-fixture",
            drift_pct=abs(319.87 - original_buy) / original_buy * 100.0,
        )
        sell_pid = arb_db.add_proposed_price(
            conn, before["id"], "sell_price_usd",
            stored_value=original_sell, proposed_value=399.99,
            detected_currency="USD", detected_raw="$399.99",
            source_url="https://example.invalid/round-13-fixture",
            drift_pct=abs(399.99 - original_sell) / original_sell * 100.0,
        )
        r1 = arb_db.resolve_proposed_price(conn, buy_pid, "apply")
        r2 = arb_db.resolve_proposed_price(conn, sell_pid, "apply")
        assert r1["applied"] is True and r2["applied"] is True

        after = arb_db.get_opportunity(conn, "JP-NINTENDO-SWOLED")
        assert float(after["purchase_price_usd"]) == pytest.approx(319.87)
        assert float(after["sell_price_usd"]) == pytest.approx(399.99)
    finally:
        conn.close()


def test_apply_visible_to_list_opportunities(fresh_db):
    """After applying, the parent must reflect the change in
    ``db.list_opportunities`` — i.e. the UPDATE was committed (not just
    visible in a fresh get_opportunity read in the same connection)."""
    conn = arb_db.connect(fresh_db)
    try:
        before = arb_db.get_opportunity(conn, "JP-DYSON-V12S")
        pid = arb_db.add_proposed_price(
            conn, before["id"], "sell_price_usd",
            stored_value=float(before["sell_price_usd"]),
            proposed_value=649.99,
            detected_currency="USD", detected_raw="$649.99",
            source_url="https://example.invalid/round-13-fixture",
            drift_pct=abs(649.99 - float(before["sell_price_usd"]))
                     / float(before["sell_price_usd"]) * 100.0,
        )
        assert arb_db.resolve_proposed_price(conn, pid, "apply")["applied"] is True
        conn.commit()
        conn.close()

        # Re-open a fresh connection — the persisted state must survive
        # a close/reopen cycle (proves the commit hit disk).
        conn2 = arb_db.connect(fresh_db)
        try:
            rows = arb_db.list_opportunities(conn2)
            dyson = next(r for r in rows if r["sku"] == "JP-DYSON-V12S")
            assert float(dyson["sell_price_usd"]) == pytest.approx(649.99), (
                "applied sell_price_usd must survive close/reopen "
                "(was 620.00 in seed; expected 649.99 after apply)"
            )
        finally:
            conn2.close()
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass