"""Round 16 follow-on — regenerate web/data-snapshot.js with fresh decisions.

The embedded snapshot at web/data-snapshot.js is what the SPA uses as an
offline fallback (and for the PICK ranking when the user hasn't clicked an
opp yet). It was baked on 2026-07-26 using the old resale model; after
Round 13 switched to the self-use/payback model, the snapshot is stale —
clicking an opp still works (live /api/decide call), but the PICK cards
and the no-click detail render still show the old numbers.

This script regenerates the ``reports`` section by calling the live
``decide_for_full`` for every opportunity at num_units in {1, 5, 50}, with
the canonical PVG-NRT-LAX-2N route. The ``opportunities`` and ``routes``
arrays are left as-is (they mirror the DB rows, no change needed).

After this runs, the SPA's PICK ranking + offline fallback reflect the
new self-use/payback model and the Round 16 home_price_cny backfill.

Run:
    python3 scripts/regenerate_snapshot.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arb import db  # noqa: E402
from arb.report import decide_for_full  # noqa: E402

SNAPSHOT_PATH = ROOT / "web" / "data-snapshot.js"
NUM_UNITS_CHOICES = (1, 5, 50)
# Local default route: matches the current DB seed (see arb/seed.py).
# Earlier worktrees used PEK-NRT-2N; this repo's working DB has
# PVG-NRT-LAX-2N as the only route, so we snapshot against that.
DEFAULT_ROUTE = "PVG-NRT-LAX-2N"


def _decision_to_dict(d) -> dict:
    """Flatten a Decision + scenario info into a JSON-friendly dict matching
    the shape the SPA expects in ``EMBEDDED_DATA.reports[sku][str(n)]``.
    """
    return d.as_dict()


def regenerate(conn) -> dict:
    opps = [dict(r) for r in db.list_opportunities(conn)]
    new_reports: dict[str, dict] = {}
    failures: list[str] = []

    for opp in opps:
        sku = opp["sku"]
        per_sku: dict[str, dict] = {}
        for n in NUM_UNITS_CHOICES:
            try:
                _o, _r, decision, _legs, _scenarios = decide_for_full(
                    conn, sku, n, DEFAULT_ROUTE,
                )
                per_sku[str(n)] = {"decision": _decision_to_dict(decision)}
            except Exception as e:  # noqa: BLE001
                failures.append(f"{sku}@{n}: {e}")
        new_reports[sku] = per_sku

    return {"reports": new_reports, "failures": failures}


def patch_snapshot_file(new_reports: dict[str, dict]) -> None:
    """Splice the new reports into the existing data-snapshot.js, leaving
    the opportunities / routes arrays untouched. Updates snapshot_at.
    """
    text = SNAPSHOT_PATH.read_text()
    fresh_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_at_line = f'  "snapshot_at": "{fresh_at}",'

    # Update snapshot_at.
    text = re.sub(
        r'  "snapshot_at":\s*"[^"]+",',
        new_at_line,
        text,
        count=1,
    )

    # Replace the entire "reports": { ... } block. The block opens at the
    # line that begins with `  "reports": {` and closes at the matching
    # `  }` before the final `};`.
    new_reports_json = json.dumps(
        new_reports, ensure_ascii=False, indent=4,
    )
    # Indent each line to match the surrounding 2-space indent.
    indented = "\n".join("    " + line for line in new_reports_json.split("\n"))

    # Find the reports block (greedy across newlines).
    pattern = re.compile(
        r'  "reports":\s*\{.*?^\s*\};\s*$',
        re.DOTALL | re.MULTILINE,
    )
    if not pattern.search(text):
        raise RuntimeError(
            "Could not locate the 'reports' block in data-snapshot.js — "
            "file format may have changed."
        )
    replacement = f'  "reports": {indented}\n}};\n'
    text = pattern.sub(replacement, text, count=1)

    SNAPSHOT_PATH.write_text(text)
    print(f"Patched {SNAPSHOT_PATH.name}: snapshot_at -> {fresh_at}")
    print(f"  reports section: {len(new_reports)} SKUs × {len(NUM_UNITS_CHOICES)} num_units")


def main() -> int:
    conn = db.connect()
    try:
        result = regenerate(conn)
    finally:
        conn.close()

    failures = result["failures"]
    if failures:
        print(f"  {len(failures)} failures (kept going):")
        for f in failures[:5]:
            print(f"    - {f}")
        if len(failures) > 5:
            print(f"    ... and {len(failures) - 5} more")

    patch_snapshot_file(result["reports"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
