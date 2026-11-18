from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from domain.budget import BudgetExceeded, BudgetLimits, BudgetReason, BudgetUsage, ExecutionBudget


def test_rate_refills_at_the_boundary_up_to_burst_limit():
    clock = Mock(return_value=0.0)
    budget = ExecutionBudget(BudgetLimits(burst=2, operations_per_second=2), clock=clock)
    for _ in range(2):
        with budget.operation():
            budget.charge_attempt()

    for tick in (0.0, 0.49):
        clock.return_value = tick
        with pytest.raises(BudgetExceeded) as error, budget.operation():
            pytest.fail("Operation should not reach I/O")
        assert error.value.reason is BudgetReason.RATE

    clock.return_value = 0.5
    with budget.operation():
        budget.charge_attempt()
    assert budget.usage() == BudgetUsage(3, 0)


def test_absolute_deadline_is_exclusive_even_for_an_admitted_operation():
    clock = Mock(return_value=100.0)
    budget = ExecutionBudget(BudgetLimits(max_seconds=2), clock=clock)
    with budget.operation():
        clock.return_value = 101.75
        assert budget.remaining_seconds() == 0.25
        clock.return_value = 102.0
        with pytest.raises(BudgetExceeded) as error:
            budget.charge_attempt()
        assert error.value.reason is BudgetReason.DEADLINE
    assert budget.usage() == BudgetUsage(0, 0)


def test_concurrent_slots_are_released_after_failure():
    budget = ExecutionBudget(BudgetLimits(burst=3, max_concurrent=1))
    with pytest.raises(RuntimeError), budget.operation():
        with pytest.raises(BudgetExceeded) as error, budget.operation():
            pytest.fail("Concurrent operation should not start")
        assert error.value.reason is BudgetReason.CONCURRENCY
        raise RuntimeError("fixture aborted")

    with budget.operation():
        budget.charge_attempt()
    assert budget.usage() == BudgetUsage(1, 0)


def test_operation_debits_are_atomic():
    budget = ExecutionBudget(BudgetLimits(max_operations=4))

    def attempt(_):
        try:
            budget.charge_attempt()
        except BudgetExceeded as error:
            assert error.reason is BudgetReason.OPERATIONS
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        allowed = sum(executor.map(attempt, range(24)))
    assert allowed == budget.usage().operations == 4


def test_fragmented_reads_cannot_exceed_byte_budget_and_refund_unused_capacity():
    budget = ExecutionBudget(BudgetLimits(max_bytes=10))
    receive = Mock(side_effect=[2, 5])
    budget.charge_write(3)

    assert budget.read(4096, receive) == 2
    receive.assert_called_once_with(7)
    assert budget.read(4096, receive) == 5
    assert receive.call_args.args == (5,)
    with pytest.raises(BudgetExceeded) as error:
        budget.read(1, receive)
    assert error.value.reason is BudgetReason.BYTES
    assert receive.call_count == 2
    assert budget.usage() == BudgetUsage(0, 10)
