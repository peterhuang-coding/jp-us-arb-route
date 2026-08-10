import json
import math
from pathlib import Path

import pytest

from arb.decision import DecisionInputs, judge


FIXTURE = Path(__file__).parent / "fixtures" / "decision_samples.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_decision_sample(case):
    inputs = DecisionInputs(**case["inputs"])
    result = judge(inputs)
    exp = case["expected"]

    # Level
    assert result.level == exp["level"], (
        f"{case['name']}: level {result.level} != {exp['level']}"
    )

    # Numeric fields — handle 'inf' marker for payback_rate_pct
    def _close(actual, expected, tol=0.5):
        if expected == "inf":
            return math.isinf(actual) and actual > 0
        if expected == "-inf":
            return math.isinf(actual) and actual < 0
        return abs(actual - expected) < tol

    assert _close(result.roi_pct, exp["roi_pct"]), (
        f"{case['name']}: roi_pct {result.roi_pct} != {exp['roi_pct']}"
    )
    assert _close(result.net_profit_usd, exp["net_profit_usd"], tol=1.0)
    assert _close(result.payback_rate_pct, exp["payback_rate_pct"])
    assert _close(result.total_savings_usd, exp["total_savings_usd"], tol=1.0)
    assert _close(result.trip_net_value_usd, exp["trip_net_value_usd"], tol=1.0)
    assert _close(result.breakeven_sell_price_usd, exp["breakeven_sell_price_usd"], tol=1.0)

    # Reason must contain the expected substring
    assert exp["reason_contains"] in result.reason, (
        f"{case['name']}: reason {result.reason!r} missing {exp['reason_contains']!r}"
    )
