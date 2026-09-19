#!/usr/bin/env python3
"""Stdlib-only benchmark for scripts/bench_algorithm_basket.py."""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import statistics
import sys
import time
import tracemalloc
from decimal import Decimal
from pathlib import Path


def load_module(path: str):
    spec = importlib.util.spec_from_file_location("bench_basket_module", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    # Register before execution so relative/import-time resolution and the
    # returned module object behave like a normally imported module.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def make_item(mod, sku: str, cost: Decimal, saving: Decimal, units: int):
    c = float(cost)
    s = float(saving)
    return mod.BasketItem(
        sku=sku,
        name=sku,
        category="bench",
        jp_price_per_unit_cny=c,
        home_price_per_unit_cny=c + s,
        savings_per_unit_cny=s,
        max_units=units,
        purchase_price_usd=0.0,
        home_price_cny=c + s,
        sell_price_usd=0.0,
        fx_rate=0.14,
    )


def fixture_n12_integer(mod):
    items = []
    for i in range(12):
        # Whole-yuan realistic prices, 100-562.
        cost = Decimal(100 + 38 * i + (i % 3) * 7)
        saving = Decimal(18 + (i % 5) * 6)
        items.append(make_item(mod, f"int-{i:02d}", cost, saving, 50 if i % 2 else 10))
    return {
        "name": "n12_integer_cap5000",
        "description": "12 SKUs, integer CNY costs around 100-562, bounded 10/50 units",
        "items": items,
        "budget": 5000.0,
        "customs": 5000.0,
    }


def fixture_n24_cent(mod):
    items = []
    for i in range(24):
        # Cent-resolution synthetic prices.
        cost = Decimal(10_327 + 211 * i + 13 * (i % 7) * (i % 5)) / Decimal(100)
        saving = Decimal(1550 + 73 * i) / Decimal(100)
        items.append(make_item(mod, f"cent-{i:02d}", cost, saving, 50 if i % 2 else 10))
    return {
        "name": "n24_cent_cap5000",
        "description": "24 SKUs, cent-resolution costs around 100-160, bounded 10/50 units",
        "items": items,
        "budget": 5000.0,
        "customs": 5000.0,
    }


def fixture_n42_fine_fx(mod):
    items = []
    for i in range(42):
        # Fine FX-like tenth-cent/ten-thousandth resolution, still realistic cost.
        cost = Decimal(
            1_024_300 + 118_750 * i + 917 * ((i * 17) % 31)
        ) / Decimal(10_000)
        saving = Decimal(142_500 + 6_250 * i + 317 * ((i * 11) % 19)) / Decimal(10_000)
        items.append(make_item(mod, f"fx-{i:02d}", cost, saving, 50 if i % 2 else 10))
    return {
        "name": "n42_fine_fx_cap5000",
        "description": "42 SKUs, fine FX-resolution costs around 100-600, bounded 10/50 units",
        "items": items,
        "budget": 5000.0,
        "customs": 5000.0,
    }


FIXTURES = {
    "n12_integer": fixture_n12_integer,
    "n24_cent": fixture_n24_cent,
    "n42_fine_fx": fixture_n42_fine_fx,
}


def exact_selected_spend(sol):
    return sum(
        (Decimal(str(pick.jp_price_per_unit_cny)) * pick.num_units for pick in sol.picks),
        Decimal("0"),
    )


def exact_selected_savings(sol):
    return sum(
        (Decimal(str(pick.savings_per_unit_cny)) * pick.num_units for pick in sol.picks),
        Decimal("0"),
    )


def bounded_failure(exc):
    return f"bounded_failure: {type(exc).__name__}: {exc}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--module-path", default="arb/basket.py")
    ap.add_argument(
        "--fixture",
        choices=["all", *FIXTURES],
        default="all",
        help="select one synthetic fixture or all three",
    )
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument(
        "--memory",
        action="store_true",
        help="perform one additional separate run under tracemalloc",
    )
    args = ap.parse_args()

    repeat = max(1, args.repeat)
    mod = load_module(str(Path(args.module_path)))
    names = list(FIXTURES) if args.fixture == "all" else [args.fixture]
    output = []

    for name in names:
        fx = FIXTURES[name](mod)
        record = {
            "fixture": fx["name"],
            "description": fx["description"],
            "repeat": repeat,
        }

        try:
            times = []
            last = None
            # Timed runs are not traced so instrumentation does not distort runtime.
            for _ in range(repeat):
                t0 = time.perf_counter()
                last = mod.solve_basket(
                    fx["items"],
                    budget_cny=fx["budget"],
                    customs_limit_cny=fx["customs"],
                )
                times.append(time.perf_counter() - t0)

            cap = min(
                Decimal(str(fx["budget"])),
                Decimal(str(fx["customs"])),
            )
            spend = exact_selected_spend(last)
            savings = exact_selected_savings(last)

            record.update(
                {
                    "median_seconds": statistics.median(times),
                    "feasible": spend <= cap,
                    "total_spend_cny": last.total_spend_cny,
                    "total_savings_cny": last.total_savings_cny,
                    "algorithm": last.algorithm,
                    "skipped_skus": list(last.skipped_skus),
                    # Benchmark has no independent oracle; therefore it reports
                    # feasibility only and deliberately does not claim optimality.
                    "optimality_verified": False,
                }
            )

            if args.memory:
                # Memory is measured in a separate single run, not in timed runs.
                with contextlib.redirect_stdout(None):
                    tracemalloc.start()
                    try:
                        mod.solve_basket(
                            fx["items"],
                            budget_cny=fx["budget"],
                            customs_limit_cny=fx["customs"],
                        )
                        _, peak = tracemalloc.get_traced_memory()
                    finally:
                        tracemalloc.stop()
                record["tracemalloc_peak_bytes"] = peak
        except Exception as exc:  # benchmark/reporting must not fabricate results
            record["bounded_failure"] = bounded_failure(exc)

        output.append(record)

    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
