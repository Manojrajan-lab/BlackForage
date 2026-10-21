import pytest

from blockforge.consensus import difficulty as diff
from blockforge.consensus.params import COIN, DEV, MAINNET, TESTNET
from blockforge.consensus.pow import bits_to_target
from blockforge.consensus.rewards import (MAX_HALVINGS, block_subsidy,
                                          coinbase_value_valid, supply_at_height)
from blockforge.core.genesis import build_genesis_block, verify_genesis


@pytest.mark.parametrize("p", [DEV, TESTNET, MAINNET])
def test_genesis_deterministic_and_valid(p):
    a, b = build_genesis_block(p), build_genesis_block(p)
    assert a.hash == b.hash and verify_genesis(a, p)
    assert a.header.height == 0 and a.transactions[0].amount == p.initial_reward


def test_genesis_differs_per_network():
    assert build_genesis_block(DEV).hash != build_genesis_block(TESTNET).hash


def test_subsidy_halving_schedule():
    p = DEV
    assert block_subsidy(p, 0) == 50 * COIN
    assert block_subsidy(p, p.halving_interval - 1) == 50 * COIN
    assert block_subsidy(p, p.halving_interval) == 25 * COIN
    assert block_subsidy(p, p.halving_interval * MAX_HALVINGS) == 0


@pytest.mark.parametrize("p", [DEV, TESTNET, MAINNET])
def test_supply_never_exceeds_cap(p):
    assert p.max_issuable() <= p.max_supply
    assert supply_at_height(p, p.halving_interval * 80) <= p.max_supply


def test_coinbase_value_rule():
    assert coinbase_value_valid(DEV, 1, 7, 50 * COIN + 7)
    assert not coinbase_value_valid(DEV, 1, 7, 50 * COIN + 8)


def test_difficulty_stays_between_retargets():
    assert diff.next_required_bits(DEV, 5, prev_bits=DEV.initial_bits) == DEV.initial_bits
    assert diff.next_required_bits(DEV, 0) == DEV.initial_bits


def test_retarget_clamps_and_limits():
    p = TESTNET
    exp = diff.expected_timespan(p)
    base = p.initial_bits
    same = diff.calculate_next_bits(p, base, 0, exp)
    assert bits_to_target(same) == pytest.approx(bits_to_target(base), rel=1e-3)
    fast = diff.calculate_next_bits(p, base, 0, 1)             # blocks far too fast
    assert bits_to_target(fast) * p.retarget_clamp <= bits_to_target(base) * 1.001
    slow = diff.calculate_next_bits(p, base, 0, exp * 100)     # far too slow
    assert bits_to_target(slow) <= p.max_target                # never easier than the limit
    with pytest.raises(ValueError):
        diff.next_required_bits(p, p.retarget_interval, prev_bits=base)  # needs timestamps


def test_slow_chain_cannot_exceed_pow_limit():
    bits = DEV.initial_bits
    assert diff.calculate_next_bits(DEV, bits, 0, 10 ** 9) == bits