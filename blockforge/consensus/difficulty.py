"""Difficulty retargeting. Pure integer math so every node computes identical results.

All values come from ConsensusParams, so dev/testnet/mainnet each retarget
with their own interval and block time.
"""
from __future__ import annotations

from typing import Optional

from blockforge.consensus.params import ConsensusParams
from blockforge.consensus.pow import bits_to_target, is_valid_bits, target_to_bits


def expected_timespan(params: ConsensusParams) -> int:
    """A window of `retarget_interval` blocks has (interval - 1) gaps between
    its first and last timestamps."""
    return (params.retarget_interval - 1) * params.target_block_time


def is_retarget_height(params: ConsensusParams, height: int) -> bool:
    """True if a block at this height starts a new difficulty period."""
    return height > 0 and height % params.retarget_interval == 0


def retarget_window_start(params: ConsensusParams, height: int) -> int:
    """Height of the first block of the window used to retarget at `height`."""
    if not is_retarget_height(params, height):
        raise ValueError("not a retarget height")
    return height - params.retarget_interval


def calculate_next_bits(params: ConsensusParams, prev_bits: int,
                        first_timestamp: int, last_timestamp: int) -> int:
    """New bits from the previous bits and the window's first/last timestamps.

    first_timestamp: timestamp of block (height - retarget_interval)
    last_timestamp:  timestamp of block (height - 1)
    """
    if not is_valid_bits(prev_bits):
        raise ValueError("invalid previous bits")

    expected = expected_timespan(params)
    timespan = last_timestamp - first_timestamp
    timespan = max(expected // params.retarget_clamp,
                   min(expected * params.retarget_clamp, timespan))

    new_target = bits_to_target(prev_bits) * timespan // expected
    new_target = max(1, min(new_target, params.max_target))

    # Round-trip through compact form so the result is exactly representable.
    return target_to_bits(new_target)


def next_required_bits(
    params: ConsensusParams,
    next_height: int,
    prev_bits: Optional[int] = None,
    window_first_timestamp: Optional[int] = None,
    prev_timestamp: Optional[int] = None,
) -> int:
    """Bits required for the block at `next_height`.

    prev_bits:              bits of the parent block (None only for genesis)
    window_first_timestamp: timestamp of block (next_height - retarget_interval);
                            required only at retarget heights
    prev_timestamp:         timestamp of the parent; required only at retarget heights
    """
    if next_height < 0:
        raise ValueError("height must be non-negative")
    if next_height == 0:
        return params.initial_bits
    if prev_bits is None:
        raise ValueError("prev_bits required for non-genesis blocks")
    if not is_retarget_height(params, next_height):
        return prev_bits
    if window_first_timestamp is None or prev_timestamp is None:
        raise ValueError("timestamps required at retarget height")
    return calculate_next_bits(params, prev_bits, window_first_timestamp, prev_timestamp)