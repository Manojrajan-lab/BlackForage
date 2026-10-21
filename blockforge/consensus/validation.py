"""Context-free and header-context block validation, driven by ConsensusParams.

Checks that need account state (nonce, balance, fees) are done by
storage/chainstate.py.
"""
from __future__ import annotations

from typing import Optional, Sequence

from blockforge.consensus.params import ConsensusParams
from blockforge.consensus.rewards import coinbase_value_valid
from blockforge.core.block import ZERO_HASH, Block, BlockHeader

BLOCK_VERSION = 1


class ValidationError(ValueError):
    """Raised when a block or header violates a consensus rule."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__("%s: %s" % (code, message) if message else code)
        self.code = code


def median_time_past(timestamps: Sequence[int], span: int) -> int:
    """Median of up to `span` most recent ancestor timestamps."""
    if not timestamps:
        raise ValueError("timestamps required")
    window = sorted(timestamps[-span:])
    return window[len(window) // 2]


def validate_header(
    params: ConsensusParams,
    header: BlockHeader,
    parent: Optional[BlockHeader],
    expected_bits: int,
    mtp: Optional[int],
    now: int,
) -> None:
    """parent is None only for genesis; mtp is the parent's median-time-past."""
    if header.version != BLOCK_VERSION:
        raise ValidationError("bad-version", str(header.version))

    if parent is None:
        if header.height != 0:
            raise ValidationError("bad-height", "missing parent")
        if header.prev_hash != ZERO_HASH:
            raise ValidationError("bad-prev-hash", "genesis must reference zero hash")
    else:
        if header.height != parent.height + 1:
            raise ValidationError("bad-height", str(header.height))
        if header.prev_hash != parent.hash():
            raise ValidationError("bad-prev-hash")
        if mtp is None:
            raise ValueError("mtp required when a parent exists")
        if header.timestamp <= mtp:
            raise ValidationError("time-too-old")
        if header.timestamp > now + params.max_future_drift:
            raise ValidationError("time-too-new")

    if header.bits != expected_bits:
        raise ValidationError("bad-bits")

    if not header.pow_valid():
        raise ValidationError("bad-pow")


def validate_block_structure(params: ConsensusParams, block: Block) -> None:
    txs = block.transactions
    if not txs:
        raise ValidationError("no-transactions")
    if len(txs) > params.max_block_txs:
        raise ValidationError("too-many-transactions")
    if block.size > params.max_block_bytes:
        raise ValidationError("block-too-large")

    if not txs[0].is_coinbase:
        raise ValidationError("first-tx-not-coinbase")
    for tx in txs[1:]:
        if tx.is_coinbase:
            raise ValidationError("multiple-coinbase")

    txids = [tx.txid for tx in txs]
    if len(set(txids)) != len(txids):
        raise ValidationError("duplicate-transaction")

    if not block.merkle_root_valid():
        raise ValidationError("bad-merkle-root")


def validate_coinbase_value(params: ConsensusParams, block: Block,
                            total_fees: int, coinbase_value: int) -> None:
    if not coinbase_value_valid(params, block.height, total_fees, coinbase_value):
        raise ValidationError("bad-coinbase-value")


def validate_block(
    params: ConsensusParams,
    block: Block,
    parent: Optional[BlockHeader],
    expected_bits: int,
    mtp: Optional[int],
    now: int,
    total_fees: int,
    coinbase_value: int,
) -> None:
    validate_header(params, block.header, parent, expected_bits, mtp, now)
    validate_block_structure(params, block)
    validate_coinbase_value(params, block, total_fees, coinbase_value)