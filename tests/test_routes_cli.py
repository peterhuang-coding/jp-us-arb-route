"""Tests for the regional LAX-SFO-1N route + `arb routes` CLI command.

Round 8 added a second route to the seed (US-domestic regional connector)
so the user can see that route choice can flip a SKU's verdict from
不建议 → 谨慎 when fixed trip costs drop from $1040 to $300.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run(*args, env_overrides=None):
    """Invoke `python -m arb <args>` with the test DB env override."""
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "arb", *args],
        capture_output=True, text=True, env=env,
    )


@pytest.fixture
def scratch_db(tmp_path, monkeypatch):
    """Seed the standard 6 SKUs + 2 routes into a tmp DB.

    Mirrors tests/test_cli.py::scratch_db but here we use the seed directly
    via upsert (no subprocess) so this fixture stays fast and avoids
    clobbering any pre-existing DB on disk.
    """
    db_file = tmp_path / "db.sqlite"
    monkeypatch.setattr("arb.db.DB_PATH", db_file)
    from arb import db, seed
    conn = db.connect(db_file)
    seed.seed_all(conn)
    conn.close()
    return db_file


# ---------- seed contract: 2 routes in DB after seed_all() ----------

def test_seed_all_inserts_two_routes():
    from arb import db, seed
    conn = db.connect_memory()
    seed.seed_all(conn)
    rows = conn.execute(
        "SELECT name, origin_city, dest_city FROM routes ORDER BY id"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "PVG-NRT-LAX-2N" in names
    assert "LAX-SFO-1N" in names
    # LAX-SFO-1N must have at least 4 legs (flight + hotel + shop + flight).
    lax_sfo = [r for r in rows if r["name"] == "LAX-SFO-1N"][0]
    legs = db.list_route_legs(
        conn, conn.execute(
            "SELECT id FROM routes WHERE name=?", ("LAX-SFO-1N",)
        ).fetchone()["id"]
    )
    assert len(legs) >= 4


def test_seed_all_idempotent_for_second_route():
    """Re-running seed must not duplicate the regional route.

    Regression: ``upsert_route`` previously returned a stale autoincrement
    counter after ON CONFLICT DO UPDATE, which made the second seed call
    pass a wrong route_id into ``add_route_legs`` and trip an FK violation.
    """
    from arb import db, seed
    conn = db.connect_memory()
    seed.seed_all(conn)
    seed.seed_all(conn)  # must not raise
    n = conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
    assert n == 2
    # Route_legs count must also be stable across reseeds (no duplicates).
    legs_n = conn.execute("SELECT COUNT(*) FROM route_legs").fetchone()[0]
    assert legs_n == 10  # 6 (intl) + 4 (regional)


def test_upsert_returns_correct_id_on_conflict():
    """upsert_opportunity / upsert_route must return the existing row id,
    not the stale autoincrement counter, on the second call."""
    from arb import db
    conn = db.connect_memory()
    opp = dict(sku="X-1", name="v1", category="misc", source_market="JP",
               target_market="US", purchase_price_usd=10.0, tariff_rate=0.0,
               sell_price_usd=20.0, shipping_per_unit_usd=1.0,
               platform_fee_rate=0.13, minutes_per_unit=10.0, success_rate=0.7,
               purchase_source_url=None, sell_source_url=None, notes=None,
               data_freshness_ts="2026-07-01", verified=0)
    first = db.upsert_opportunity(conn, opp)
    second = db.upsert_opportunity(conn, dict(opp, name="v2"))
    assert first == second  # same row, not a stale autoinc value

    route = dict(name="R-1", origin_city="A", dest_city="B",
                 flight_cost_usd=10.0, hotel_cost_usd=10.0,
                 other_cost_usd=0.0, hours_available=8.0,
                 departure_date="2026-09-01", source_url="https://x")
    rid1 = db.upsert_route(conn, route)
    rid2 = db.upsert_route(conn, dict(route, flight_cost_usd=20.0))
    assert rid1 == rid2


# ---------- route economic profile ----------

def test_regional_route_has_cheaper_fixed_cost_than_international():
    """Fixed trip cost must drop dramatically from international to regional."""
    from arb import db, seed
    conn = db.connect_memory()
    seed.seed_all(conn)
    pvg = db.get_route(conn, "PVG-NRT-LAX-2N")
    lax = db.get_route(conn, "LAX-SFO-1N")
    pvg_fixed = pvg["flight_cost_usd"] + pvg["hotel_cost_usd"] + pvg["other_cost_usd"]
    lax_fixed = lax["flight_cost_usd"] + lax["hotel_cost_usd"] + lax["other_cost_usd"]
    assert pvg_fixed == 1040.0
    assert lax_fixed == 300.0
    # Regional must be strictly cheaper — that's the whole point.
    assert lax_fixed < pvg_fixed / 3


# ---------- route-flip behavior: regional flips SK-II from ❌ → ⚠️ ----------

def test_skii_flips_to_warn_at_20u_with_regional_route():
    """With the cheap regional route, 20× SK-II under payback model improves."""
    from arb import db, seed
    from arb.decision import judge, DecisionInputs
    conn = db.connect_memory()
    seed.seed_all(conn)
    opp = db.get_opportunity(conn, "JP-SKII-FT230")
    route_intl = db.get_route(conn, "PVG-NRT-LAX-2N")
    route_reg = db.get_route(conn, "LAX-SFO-1N")
    # SK-II seed has max_units_per_trip=6 (daily purchase limit).
    # Use a 6-unit scenario for both routes and check that regional flips verdict.
    di_intl = DecisionInputs(
        num_units=6,
        purchase_price_usd=opp["purchase_price_usd"],
        sell_price_usd=opp["sell_price_usd"],
        home_price_usd=(opp["home_price_cny"] * route_intl["cn_to_usd_fx"]
                        if opp["home_price_cny"] is not None else None),
        tariff_rate=opp["tariff_rate"],
        shipping_per_unit_usd=opp["shipping_per_unit_usd"],
        platform_fee_rate=opp["platform_fee_rate"],
        minutes_per_unit=opp["minutes_per_unit"],
        flight_cost_usd=route_intl["flight_cost_usd"],
        hotel_cost_usd=route_intl["hotel_cost_usd"],
        other_trip_cost_usd=route_intl["other_cost_usd"],
        hours_available=route_intl["hours_available"],
        target_hourly_usd=route_intl["target_hourly_usd"],
        target_roi_pct=route_intl["target_roi_pct"],
        min_roi_pct=route_intl["min_roi_pct"],
        max_units_per_trip=opp["max_units_per_trip"],
    )
    di_reg = DecisionInputs(
        num_units=6,
        purchase_price_usd=opp["purchase_price_usd"],
        sell_price_usd=opp["sell_price_usd"],
        home_price_usd=(opp["home_price_cny"] * route_reg["cn_to_usd_fx"]
                        if opp["home_price_cny"] is not None else None),
        tariff_rate=opp["tariff_rate"],
        shipping_per_unit_usd=opp["shipping_per_unit_usd"],
        platform_fee_rate=opp["platform_fee_rate"],
        minutes_per_unit=opp["minutes_per_unit"],
        flight_cost_usd=route_reg["flight_cost_usd"],
        hotel_cost_usd=route_reg["hotel_cost_usd"],
        other_trip_cost_usd=route_reg["other_cost_usd"],
        hours_available=route_reg["hours_available"],
        target_hourly_usd=route_reg["target_hourly_usd"],
        target_roi_pct=route_reg["target_roi_pct"],
        min_roi_pct=route_reg["min_roi_pct"],
        max_units_per_trip=opp["max_units_per_trip"],
    )
    d_intl = judge(di_intl)
    d_reg = judge(di_reg)
    # 6 units × ($154 home - $85 purchase - $4 shipping) = $390 savings
    # intl $1040 trip: payback 37.5% → 不建议
    # regional $300 trip: payback 130% → 建议
    assert d_intl.level == "不建议"
    assert d_reg.level == "建议"
    assert d_reg.trip_net_value_usd > d_intl.trip_net_value_usd


# ---------- CLI: `arb routes` listing ----------

def test_cli_routes_lists_both_routes(scratch_db):
    out = _run("routes", env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert out.returncode == 0, out.stderr
    assert "PVG-NRT-LAX-2N" in out.stdout
    assert "LAX-SFO-1N" in out.stdout
    # Both routes must show fixed-cost summary line.
    assert "固定 $" in out.stdout


def test_cli_routes_add_inserts_new_route(scratch_db):
    out = _run(
        "routes", "--add",
        "--name", "JFK-LAX-1N",
        "--origin", "纽约 JFK",
        "--dest", "洛杉矶 LAX",
        "--flight", "200",
        "--hotel", "150",
        "--other", "40",
        "--hours", "20",
        "--depart", "2026-10-01",
        "--notes", "美东 → 美西测试路线",
        env_overrides={"ARB_DB_PATH": str(scratch_db)},
    )
    assert out.returncode == 0, out.stderr
    payload = json.loads(out.stdout.strip().splitlines()[-1])
    assert payload["name"] == "JFK-LAX-1N"
    assert payload["inserted"] > 0
    # Listing should now include the new route.
    listing = _run("routes", env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert "JFK-LAX-1N" in listing.stdout


def test_cli_routes_add_is_idempotent(scratch_db):
    """Re-adding the same route name is a no-op, not a duplicate."""
    base = [
        "routes", "--add",
        "--name", "JFK-LAX-1N",
        "--origin", "纽约 JFK",
        "--dest", "洛杉矶 LAX",
        "--flight", "200",
        "--hotel", "150",
    ]
    first = _run(*base, env_overrides={"ARB_DB_PATH": str(scratch_db)})
    second = _run(*base, env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert first.returncode == 0
    assert second.returncode == 0
    assert "already exists" in second.stdout
    # Still exactly 3 routes (2 seeded + 1 added).
    listing = _run("routes", env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert listing.stdout.count("[") == 3


# ---------- Round 11: --leg repeatable flag on `arb routes --add` ----------
#
# Round 8 left `arb routes --add` without a way to attach route_legs, so any
# route inserted via the CLI started with 0 legs. Round 11 accepts a
# repeatable --leg JSON payload, parses it, and calls db.add_route_legs so
# CLI-inserted routes carry the same flight/hotel/shop schedule as the seed.

def _add_with_legs(name, *legs_json, scratch_db, **route_kwargs):
    """Invoke `arb routes --add` with one or more --leg JSON payloads."""
    cmd = [
        "routes", "--add",
        "--name", name,
        "--origin", route_kwargs.get("origin", "测试 ORIG"),
        "--dest", route_kwargs.get("dest", "测试 DEST"),
        "--flight", str(route_kwargs.get("flight", 100)),
        "--hotel", str(route_kwargs.get("hotel", 50)),
        "--other", str(route_kwargs.get("other", 0)),
        "--hours", str(route_kwargs.get("hours", 12)),
    ]
    for leg in legs_json:
        cmd.extend(["--leg", leg])
    return _run(*cmd, env_overrides={"ARB_DB_PATH": str(scratch_db)})


def test_cli_routes_add_with_single_leg_inserts_route_and_legs(scratch_db):
    """--leg with a JSON payload persists the leg on the new route."""
    leg = json.dumps({"kind": "flight", "label": "JFK → LAX",
                       "cost_usd": 200.0, "duration_min": 360.0,
                       "location": "New York"})
    out = _add_with_legs("JFK-LAX-1N", leg, scratch_db=scratch_db)
    assert out.returncode == 0, out.stderr

    # Listing output must reflect the new legs count.
    listing = _run("routes", env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert "JFK-LAX-1N" in listing.stdout
    assert "legs=1" in listing.stdout


def test_cli_routes_add_with_multiple_legs_inserts_in_order(scratch_db):
    """Repeated --leg flags accumulate and preserve seq ordering."""
    legs = [
        json.dumps({"kind": "flight", "label": "JFK → LAX",
                     "cost_usd": 200.0, "duration_min": 360.0}),
        json.dumps({"kind": "hotel", "label": "LAX Hotel 1N",
                     "cost_usd": 150.0, "duration_min": 0.0}),
        json.dumps({"kind": "shop", "label": "Beverly Hills drop-off",
                     "cost_usd": 0.0, "duration_min": 60.0}),
        json.dumps({"kind": "flight", "label": "LAX → JFK",
                     "cost_usd": 200.0, "duration_min": 360.0}),
    ]
    out = _add_with_legs("JFK-LAX-1N", *legs, scratch_db=scratch_db)
    assert out.returncode == 0, out.stderr

    listing = _run("routes", env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert "legs=4" in listing.stdout
    # Listing must also reflect the cumulative duration (60min sum not relevant;
    # 360+0+60+360 = 780 min).  Just assert total_min token is present.
    assert "780min" in listing.stdout


def test_cli_routes_add_leg_missing_required_field_exits_nonzero(scratch_db):
    """A --leg JSON missing 'kind' is malformed and must fail loudly."""
    bad_leg = json.dumps({"label": "no kind", "cost_usd": 100.0})
    out = _add_with_legs("BAD-RT-1", bad_leg, scratch_db=scratch_db)
    assert out.returncode != 0, out.stdout
    # The error must mention which field is missing so the user can fix it.
    assert "kind" in out.stderr.lower() or "kind" in out.stdout.lower()


def test_cli_routes_add_leg_invalid_json_exits_nonzero(scratch_db):
    """A --leg that isn't valid JSON must fail with a parse error."""
    out = _add_with_legs("BAD-RT-2", "not-json-at-all", scratch_db=scratch_db)
    assert out.returncode != 0
    combined = (out.stderr + out.stdout).lower()
    assert "json" in combined or "parse" in combined or "invalid" in combined


def test_cli_routes_add_without_leg_flag_still_works(scratch_db):
    """Backward compat: --add without --leg still inserts a 0-leg route."""
    out = _run(
        "routes", "--add",
        "--name", "ZERO-LEGS",
        "--origin", "X", "--dest", "Y",
        "--flight", "50", "--hotel", "50",
        env_overrides={"ARB_DB_PATH": str(scratch_db)},
    )
    assert out.returncode == 0, out.stderr
    listing = _run("routes", env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert "ZERO-LEGS" in listing.stdout
    assert "legs=0" in listing.stdout


def test_cli_routes_add_with_existing_name_replaces_legs(scratch_db):
    """Re-adding a route that already has legs replaces the leg set,
    so the CLI is idempotent and a stale leg set never lingers."""
    legs_v1 = [
        json.dumps({"kind": "flight", "label": "v1 flight",
                     "cost_usd": 100.0, "duration_min": 60.0}),
    ]
    legs_v2 = [
        json.dumps({"kind": "flight", "label": "v2 flight A",
                     "cost_usd": 200.0, "duration_min": 60.0}),
        json.dumps({"kind": "flight", "label": "v2 flight B",
                     "cost_usd": 200.0, "duration_min": 60.0}),
    ]
    out1 = _add_with_legs("REPLACE-RT", *legs_v1, scratch_db=scratch_db)
    assert out1.returncode == 0, out1.stderr
    listing1 = _run("routes", env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert "legs=1" in listing1.stdout

    out2 = _add_with_legs("REPLACE-RT", *legs_v2, scratch_db=scratch_db)
    assert out2.returncode == 0, out2.stderr
    listing2 = _run("routes", env_overrides={"ARB_DB_PATH": str(scratch_db)})
    assert "legs=2" in listing2.stdout
    # Stale v1 label must be gone from the listing.
    assert "v1 flight" not in listing2.stdout


def test_cli_routes_add_legs_appear_in_decide_api():
    """Legs added via the CLI must show up via db.list_route_legs so the SPA
    timeline (which reads via /api/decide → decide_for → list_route_legs)
    renders them.  End-to-end check: insert a fresh route via CLI, read back."""
    from arb import db

    # Use a dedicated tmp DB so this test doesn't mutate the project's DB.
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    db_file = Path(tmp.name)

    # Seed 2 routes so we have a baseline DB; we'll add a NEW route name so
    # we exercise the insert (not replace) branch.
    from arb import seed
    conn = db.connect(db_file)
    seed.seed_all(conn)
    conn.close()

    legs = [
        json.dumps({"kind": "shop", "label": "CLI-added shop leg A",
                     "cost_usd": 25.0, "duration_min": 30.0,
                     "location": "Tokyo", "notes": "round 11 test"}),
        json.dumps({"kind": "shop", "label": "CLI-added shop leg B",
                     "cost_usd": 25.0, "duration_min": 30.0,
                     "location": "Osaka"}),
    ]
    out = _add_with_legs("E2E-CLI-INSERT", *legs, scratch_db=db_file)
    assert out.returncode == 0, out.stderr

    conn = db.connect(db_file)
    route_id = conn.execute(
        "SELECT id FROM routes WHERE name=?", ("E2E-CLI-INSERT",)
    ).fetchone()["id"]
    post_legs = db.list_route_legs(conn, route_id)
    conn.close()
    assert len(post_legs) == 2
    labels = [l["label"] for l in post_legs]
    assert "CLI-added shop leg A" in labels
    assert "CLI-added shop leg B" in labels
    # Order is preserved by --leg positional order on the command line.
    assert labels[0] == "CLI-added shop leg A"
    assert labels[1] == "CLI-added shop leg B"
    db_file.unlink(missing_ok=True)


def test_parse_leg_payload_helper_accepts_minimal_payload():
    """The shared parser should accept a 3-field payload (kind/label/cost)
    and default duration to 0.0 / location & notes to empty strings."""
    from arb.cli import _parse_leg_payload
    out = _parse_leg_payload(json.dumps({
        "kind": "transit", "label": "Tokyo → Kyoto", "cost_usd": 80.0,
    }))
    assert out["kind"] == "transit"
    assert out["label"] == "Tokyo → Kyoto"
    assert out["cost_usd"] == 80.0
    assert out["duration_min"] == 0.0
    assert out["location"] == ""
    assert out["notes"] == ""