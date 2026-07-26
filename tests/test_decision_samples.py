import json
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
    assert result.level == exp["level"], (
        f"{case['name']}: level {result.level} != {exp['level']}"
    )
    assert abs(result.roi_pct - exp["roi_pct"]) < 0.5
    assert abs(result.net_profit_usd - exp["net_profit_usd"]) < 1.0
    assert (
        abs(
            result.breakeven_sell_price_usd
            - exp["breakeven_sell_price_usd"]
        )
        < 1.0
    )
    assert exp["reason_contains"] in result.reason
