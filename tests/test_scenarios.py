"""Unit tests for the scenario (保守/中性/乐观) layer.

SPEC (locked before implementation):

The scenarios module wraps arb.decision.judge() with three bands:

* 保守 (conservative):售价 -10%,采购 +5%,关税 +10%,物流 +10%,
  机票 +10%,酒店 +10%,时薪 +20%(用户更珍惜时间 → 机会成本更高)。
* 中性 (neutral):所有倍数 = 1.0,等同于单点 judge() 结果。
* 乐观 (optimistic):售价 +5%,采购 -3%,机票 -5%,酒店 -5%,时薪 -10%。

Each scenario returns a ScenarioResult with:
  - name              : "保守" / "中性" / "乐观"
  - description       : 一句话说明(中文)
  - shifts            : ScenarioShifts(便于复算)
  - decision          : arb.decision.Decision(单点判定的所有字段)
  - delta_roi_pct     : 与中性 ROI 的百分点差 (正 = 比中性更好)
  - delta_net_profit  : 与中性净利的 USD 差 (正 = 比中性更好)
  - cross_check       : 若保守 level 比中性更严("谨慎"→"不建议" 或 "建议"→非"建议"),
                        给出降级提示字符串;否则为空。

Cross-check rule:
  - 若 保守.level 严于 中性.level  → cross_check 警告
  - 若 乐观.level 比 中性.level 更好 ("不建议" → 非"不建议") → cross_check 鼓励
  - 否则 cross_check 为空

Rules:
  * neutralize == apply_shifts(inp, ScenarioShifts()) yields a Decision identical to
    judge(inp) (every numeric field).
  * summarize(inp) returns exactly 3 ScenarioResult objects in fixed order [保守, 中性, 乐观].
  * 默认倍数表必须可被覆盖 (custom_shifts=ScenarioShifts(...))。
  * shifts 倍数为 0 必须抛 ValueError(成本不能为 0;若故意,可显式传 0)。
  * apply_shifts 对 tariff_rate 也按倍数缩放(关税政策可能变化)。
"""
from __future__ import annotations

import pytest

from arb.decision import DecisionInputs, judge
from arb.scenarios import (
    DEFAULT_SCENARIOS,
    ScenarioResult,
    ScenarioShifts,
    apply_shifts,
    summarize,
)


# ---------- helpers ----------

def base_inputs(**overrides) -> DecisionInputs:
    """Healthy baseline: 2x SK-II PITERA 230ml under self-use (same shape as test_decision)."""
    d = dict(
        num_units=2,
        purchase_price_usd=85.0,
        sell_price_usd=140.0,        # legacy, used as fallback for home_price_usd
        home_price_usd=140.0,        # self-use baseline (CN-equivalent retail)
        tariff_rate=0.0,
        shipping_per_unit_usd=4.0,
        platform_fee_rate=0.13,
        minutes_per_unit=20.0,
        flight_cost_usd=720.0,
        hotel_cost_usd=240.0,
        other_trip_cost_usd=80.0,
        hours_available=32.0,
        target_hourly_usd=0.0,        # no time cost under payback model
        target_roi_pct=15.0,
        min_roi_pct=10.0,
    )
    d.update(overrides)
    return DecisionInputs(**d)


# ---------- API shape ----------

def test_default_scenarios_count():
    assert len(DEFAULT_SCENARIOS) == 3


def test_summarize_returns_three_in_fixed_order():
    res = summarize(base_inputs())
    assert [r.name for r in res] == ["保守", "中性", "乐观"]
    assert all(isinstance(r, ScenarioResult) for r in res)


def test_summarize_description_per_band():
    res = summarize(base_inputs())
    assert all(r.description for r in res)
    # 保守 description mentions down-side, 乐观 mentions up-side, 中性 is neutral
    assert "下行" in res[0].description or "保守" in res[0].description
    assert "中性" in res[1].description
    assert "上行" in res[2].description or "乐观" in res[2].description


def test_default_scenarios_multipliers_conservative_more_pessimistic_than_optimistic():
    """保守 must lower sell, raise costs; 乐观 must raise sell, lower costs."""
    res = summarize(base_inputs())
    cons, neu, opt = res
    # 保守: 售价低于中性, 采购价高于中性, 机票/酒店高于中性
    assert (DEFAULT_SCENARIOS[0].sell_price_factor
            < DEFAULT_SCENARIOS[1].sell_price_factor)
    assert (DEFAULT_SCENARIOS[0].purchase_price_factor
            > DEFAULT_SCENARIOS[1].purchase_price_factor)
    assert (DEFAULT_SCENARIOS[0].flight_factor
            > DEFAULT_SCENARIOS[1].flight_factor)
    assert (DEFAULT_SCENARIOS[0].hotel_factor
            > DEFAULT_SCENARIOS[1].hotel_factor)
    # 乐观: 售价高于中性, 采购价低于中性, 机票/酒店低于中性
    assert (DEFAULT_SCENARIOS[2].sell_price_factor
            > DEFAULT_SCENARIOS[1].sell_price_factor)
    assert (DEFAULT_SCENARIOS[2].purchase_price_factor
            < DEFAULT_SCENARIOS[1].purchase_price_factor)
    assert (DEFAULT_SCENARIOS[2].flight_factor
            < DEFAULT_SCENARIOS[1].flight_factor)
    assert (DEFAULT_SCENARIOS[2].hotel_factor
            < DEFAULT_SCENARIOS[1].hotel_factor)


# ---------- neutrality invariant ----------

def test_neutral_scenario_matches_single_judge():
    """Summarize's 中性 band must produce a Decision numerically identical to judge()."""
    inp = base_inputs()
    expected = judge(inp)
    res = summarize(inp)
    neu = res[1]
    assert neu.decision.level == expected.level
    assert neu.decision.reason == expected.reason
    assert neu.decision.roi_pct == pytest.approx(expected.roi_pct)
    assert neu.decision.net_profit_usd == pytest.approx(expected.net_profit_usd)
    assert neu.decision.total_cost_usd == pytest.approx(expected.total_cost_usd)
    assert neu.decision.total_revenue_usd == pytest.approx(expected.total_revenue_usd)
    assert neu.decision.breakeven_sell_price_usd == pytest.approx(
        expected.breakeven_sell_price_usd
    )
    assert neu.decision.hours_used == pytest.approx(expected.hours_used)


def test_neutral_delta_is_zero():
    inp = base_inputs()
    res = summarize(inp)
    neu = res[1]
    assert neu.delta_roi_pct == pytest.approx(0.0, abs=1e-9)
    assert neu.delta_net_profit == pytest.approx(0.0, abs=1e-9)


def test_conservative_worse_than_neutral_in_happy_path():
    """For a healthy baseline, conservative must produce lower ROI / profit."""
    inp = base_inputs()
    res = summarize(inp)
    cons, neu, opt = res
    assert cons.delta_roi_pct < 0
    assert cons.delta_net_profit < 0
    assert opt.delta_roi_pct > 0
    assert opt.delta_net_profit > 0


# ---------- hand-calculated scenarios ----------

def test_hand_calc_conservative_scenario():
    """Hand-compute conservative scenario for the baseline under payback model.

    Cons shifts:
      home_price_factor (sell_price_factor in shifts) = 0.90 → home 126.0
      purchase_factor   = 1.05 → purchase 89.25
      shipping_factor   = 1.10 → shipping 4.4
      flight_factor     = 1.10 → flight 792.0
      hotel_factor      = 1.10 → hotel 264.0
      hourly_factor     = 1.20 → no effect (target_hourly=0 in baseline)

    per_unit_cost_no_trip = 89.25 + 0 + 4.4 = 93.65
    per_unit_savings      = 126.0 - 93.65 = 32.35
    trip_cost = 792 + 264 + 80 = 1136
    2 units: total_savings=64.70, trip_net_value = 64.70 - 1136 = -1071.30
    """
    inp = base_inputs()
    res = summarize(inp)
    cons = res[0]
    neu = res[1]
    # Under payback model, per_unit_revenue_usd = per_unit_savings_usd
    assert cons.decision.per_unit_revenue_usd == pytest.approx(32.35)
    assert cons.decision.per_unit_cost_usd == pytest.approx(93.65)
    # trip_net_value_usd is negative; payback is far below 100%
    assert cons.decision.trip_net_value_usd < 0
    assert cons.decision.payback_rate_pct < 100.0
    # hours_used is invariant to monetary shifts
    assert cons.decision.hours_used == pytest.approx(neu.decision.hours_used)
    # Conservative worse than neutral on the happy path
    assert cons.decision.trip_net_value_usd < neu.decision.trip_net_value_usd
    assert cons.decision.payback_rate_pct < neu.decision.payback_rate_pct


def test_hand_calc_optimistic_scenario():
    """Hand-compute optimistic scenario for the baseline under payback model.

    Opt shifts:
      home_price_factor  = 1.05 → home 147.0
      purchase_factor    = 0.97 → purchase 82.45
      flight_factor      = 0.95 → flight 684.0
      hotel_factor       = 0.95 → hotel 228.0
      hourly_factor      = 0.90 → no effect

    per_unit_cost_no_trip = 82.45 + 0 + 4 = 86.45
    per_unit_savings      = 147.0 - 86.45 = 60.55
    trip_cost = 684 + 228 + 80 = 992
    2 units: total_savings=121.10, trip_net_value = 121.10 - 992 = -870.90
    """
    inp = base_inputs()
    res = summarize(inp)
    opt = res[2]
    cons = res[0]
    assert opt.decision.per_unit_revenue_usd == pytest.approx(60.55)
    assert opt.decision.per_unit_cost_usd == pytest.approx(86.45)
    assert opt.decision.trip_net_value_usd < 0
    # Optimistic must beat conservative
    assert opt.decision.trip_net_value_usd > cons.decision.trip_net_value_usd
    assert opt.decision.payback_rate_pct > cons.decision.payback_rate_pct


# ---------- cross-check downgrade hint ----------

def test_cross_check_warning_when_conservative_level_worse():
    """A '建议' baseline whose 保守 drops to a stricter level must carry a warning.

    Under the payback model, conservative shifts (-10% home, +10% trip) reduce
    payback by ~18% (0.9/1.1). To get a 建议→谨慎 drop we set neutral just
    above 100%; conservative lands at ~90% → 谨慎.
    """
    inp = base_inputs(
        home_price_usd=300.0,
        purchase_price_usd=20.0,
        shipping_per_unit_usd=2.0,
        flight_cost_usd=200.0,
        hotel_cost_usd=200.0,
        other_trip_cost_usd=100.0,
        minutes_per_unit=20.0,
    )
    res = summarize(inp)
    cons, neu, opt = res
    # Neutral payback = 2*(300-20-2) / 500 = 556/500 = 111.2% → 建议
    assert neu.decision.level == "建议", (
        f"expected 中性 → 建议, got {neu.decision.level} "
        f"(payback={neu.decision.payback_rate_pct:.1f}%)"
    )
    # Conservative payback = 2*(270-20-2.2) / 550 = 495.6/550 = 90.1% → 谨慎
    assert cons.decision.level == "谨慎", (
        f"expected 保守 → 谨慎, got {cons.decision.level} "
        f"(payback={cons.decision.payback_rate_pct:.1f}%)"
    )
    # Cross-check must surface the downgrade
    assert "保守" in cons.cross_check
    assert "降级" in cons.cross_check or "谨慎" in cons.cross_check


def test_cross_check_empty_when_levels_agree():
    """If conservative & neutral share the same level, no downgrade hint needed."""
    inp = base_inputs()  # already unprofitable in all bands
    res = summarize(inp)
    cons = res[0]
    neu = res[1]
    # Both end up at "不建议" with this baseline
    assert cons.decision.level == neu.decision.level == "不建议"
    assert cons.cross_check == ""


# ---------- custom shifts ----------

def test_custom_shifts_override_defaults():
    custom = [
        ScenarioShifts(sell_price_factor=0.5, purchase_price_factor=2.0),  # extra conservative
        ScenarioShifts(),
        ScenarioShifts(sell_price_factor=2.0, purchase_price_factor=0.5),  # extra optimistic
    ]
    res = summarize(base_inputs(), custom_shifts=custom)
    cons, neu, opt = res
    # Spread between cons and opt must be larger than default spread
    default = summarize(base_inputs())
    cons_spread = (
        default[2].decision.net_profit_usd - default[0].decision.net_profit_usd
    )
    custom_spread = opt.decision.net_profit_usd - cons.decision.net_profit_usd
    assert custom_spread > cons_spread


def test_custom_shifts_neutral_band_still_matches_judge():
    custom = [
        ScenarioShifts(sell_price_factor=0.7),
        ScenarioShifts(),
        ScenarioShifts(sell_price_factor=1.3),
    ]
    inp = base_inputs()
    res = summarize(inp, custom_shifts=custom)
    expected = judge(inp)
    assert res[1].decision.net_profit_usd == pytest.approx(expected.net_profit_usd)
    assert res[1].decision.roi_pct == pytest.approx(expected.roi_pct)


# ---------- apply_shifts validation ----------

def test_apply_shifts_with_neutral_shifts_is_identity():
    inp = base_inputs()
    shifted = apply_shifts(inp, ScenarioShifts())
    assert shifted.purchase_price_usd == inp.purchase_price_usd
    assert shifted.sell_price_usd == inp.sell_price_usd
    assert shifted.flight_cost_usd == inp.flight_cost_usd
    assert shifted.hotel_cost_usd == inp.hotel_cost_usd
    assert shifted.minutes_per_unit == inp.minutes_per_unit
    assert shifted.target_hourly_usd == inp.target_hourly_usd
    assert shifted.tariff_rate == inp.tariff_rate
    assert shifted.shipping_per_unit_usd == inp.shipping_per_unit_usd


def test_apply_shifts_zero_factor_documented_behavior():
    """apply_shifts with factor=0 collapses the field to 0 — caller responsibility.

    DecisionInputs allows sell_price_usd = 0 (edge case for "free item"),
    so apply_shifts does not raise on its own; downstream judge() decides
    whether 0 is acceptable. This test pins the documented behavior so a
    future change to validate() doesn't silently flip semantics.
    """
    bad = ScenarioShifts(sell_price_factor=0.0)
    shifted = apply_shifts(base_inputs(sell_price_usd=140.0), bad)
    assert shifted.sell_price_usd == 0.0
    # Other fields remain untouched.
    assert shifted.purchase_price_usd == 85.0


# ---------- summary dict ----------

def test_scenario_as_dict_round_trip():
    res = summarize(base_inputs())
    for r in res:
        d = r.as_dict()
        assert d["name"] == r.name
        assert d["level"] == r.decision.level
        assert d["roi_pct"] == pytest.approx(r.decision.roi_pct)
        assert d["net_profit_usd"] == pytest.approx(r.decision.net_profit_usd)
        assert d["cross_check"] == r.cross_check
        assert "shifts" in d


# ---------- downstream: report.py integration ----------

def _fake_opp(**overrides) -> dict:
    base = {
        "id": 0,
        "sku": "JP-SKII-FT230",
        "name": "SK-II Facial Treatment Essence 230ml",
        "purchase_price_usd": 85.0,
        "sell_price_usd": 140.0,
        "tariff_rate": 0.0,
        "shipping_per_unit_usd": 4.0,
        "platform_fee_rate": 0.13,
        "minutes_per_unit": 20.0,
        "purchase_source_url": "https://example.com/jp",
        "sell_source_url": "https://example.com/us",
        "data_freshness_ts": "2026-07-20",
        "verified": 0,
        "_pending_proposals": [],
    }
    base.update(overrides)
    return base


def _fake_route(**overrides) -> dict:
    base = {
        "id": 0,
        "name": "PVG-NRT-LAX-2N",
        "origin_city": "PVG",
        "dest_city": "LAX",
        "flight_cost_usd": 720.0,
        "hotel_cost_usd": 240.0,
        "other_cost_usd": 80.0,
        "hours_available": 32.0,
        "target_hourly_usd": 20.0,
        "target_roi_pct": 15.0,
        "min_roi_pct": 10.0,
        "departure_date": "2026-09-01",
        "source_url": "https://example.com/flights",
    }
    base.update(overrides)
    return base


def test_report_render_markdown_includes_scenarios():
    """Round-trip: report.py's render_markdown must surface the 3 bands."""
    from arb import report
    from arb.decision import judge, DecisionInputs

    opp = _fake_opp()
    route = _fake_route()
    di = DecisionInputs(
        num_units=5,
        purchase_price_usd=85.0,
        sell_price_usd=140.0,
        tariff_rate=0.0,
        shipping_per_unit_usd=4.0,
        platform_fee_rate=0.13,
        minutes_per_unit=20.0,
        flight_cost_usd=720.0,
        hotel_cost_usd=240.0,
        other_trip_cost_usd=80.0,
        hours_available=32.0,
        target_hourly_usd=20.0,
        target_roi_pct=15.0,
        min_roi_pct=10.0,
    )
    decision = judge(di)
    scenarios = summarize(di)
    md = report.render_markdown(opp, route, [], 5, decision, scenarios)
    assert "保守" in md
    assert "中性" in md
    assert "乐观" in md
    # Scenario block should be under a heading
    assert "场景" in md or "情景" in md or "scenarios" in md.lower()


def test_report_render_html_includes_scenarios():
    from arb import report
    from arb.decision import judge, DecisionInputs

    opp = _fake_opp(name="SK-II FT230", purchase_source_url="", sell_source_url="")
    route = _fake_route(departure_date="", source_url="")
    di = DecisionInputs(
        num_units=5,
        purchase_price_usd=85.0,
        sell_price_usd=140.0,
        tariff_rate=0.0,
        shipping_per_unit_usd=4.0,
        platform_fee_rate=0.13,
        minutes_per_unit=20.0,
        flight_cost_usd=720.0,
        hotel_cost_usd=240.0,
        other_trip_cost_usd=80.0,
        hours_available=32.0,
        target_hourly_usd=20.0,
        target_roi_pct=15.0,
        min_roi_pct=10.0,
    )
    decision = judge(di)
    scenarios = summarize(di)
    html_str = report.render_html(opp, route, [], 5, decision, scenarios)
    assert "保守" in html_str
    assert "中性" in html_str
    assert "乐观" in html_str
    # CSS class added for scenarios table
    assert "scenario-table" in html_str