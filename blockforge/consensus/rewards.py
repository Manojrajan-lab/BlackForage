"""Block subsidy schedule and supply accounting. All amounts are integer base units."""
from __future__ import annotations

from blockforge.consensus.params import ConsensusParams

MAX_HALVINGS = 64  # after this many halvings the subsidy is zero


def halvings_at(params: ConsensusParams, height: int) -> int:
    if height < 0:
        raise ValueError("height must be non-negative")
    return height // params.halving_interval


def block_subsidy(params: ConsensusParams, height: int) -> int:
    """Newly issued base units for a block at this height."""
    halvings = halvings_at(params, height)
    if halvings >= MAX_HALVINGS:
        return 0
    return params.initial_reward >> halvings


def max_coinbase_value(params: ConsensusParams, height: int, total_fees: int) -> int:
    if total_fees < 0:
        raise ValueError("total_fees must be non-negative")
    return block_subsidy(params, height) + total_fees


def coinbase_value_valid(params: ConsensusParams, height: int,
                         total_fees: int, coinbase_value: int) -> bool:
    if coinbase_value < 0 or total_fees < 0:
        return False
    return coinbase_value <= max_coinbase_value(params, height, total_fees)


def supply_at_height(params: ConsensusParams, height: int) -> int:
    """Total subsidy issued by blocks 0..height inclusive."""
    if height < 0:
        return 0
    total, remaining, era = 0, height + 1, 0
    while remaining > 0 and era < MAX_HALVINGS:
        blocks = min(remaining, params.halving_interval)
        total += blocks * (params.initial_reward >> era)
        remaining -= blocks
        era += 1
    return total


def is_coinbase_mature(params: ConsensusParams, coinbase_height: int, spend_height: int) -> bool:
    return spend_height - coinbase_height >= params.coinbase_maturity