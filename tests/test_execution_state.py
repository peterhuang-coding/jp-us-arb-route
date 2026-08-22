"""M0 状态机核心测试."""
from arb.execution.state import NEXT_STATE, OrderState


def test_next_state_chain_is_linear():
    states = [OrderState.CREATED, OrderState.LISTED, OrderState.ORDER_PAID,
              OrderState.FUNDS_VERIFIED, OrderState.SOURCING, OrderState.PURCHASED,
              OrderState.PAID, OrderState.WAREHOUSED, OrderState.AWAITING_FLIGHT,
              OrderState.SHIPPED, OrderState.COMPLETED]
    for cur, nxt in zip(states, states[1:]):
        assert NEXT_STATE[cur] is nxt


def test_terminal_states_have_no_next():
    for s in (OrderState.COMPLETED, OrderState.AWAITING_HUMAN, OrderState.CANCELLED):
        assert NEXT_STATE[s] is None


def test_all_states_covered_by_table():
    assert set(NEXT_STATE) == set(OrderState)
