"""Deterministic genesis block, mined with real proof-of-work.

Every input comes from ConsensusParams, and the nonce search always starts at
0, so every node derives the identical genesis block for a given network.
The genesis coinbase pays a key hash derived from a fixed string: no private
key is known for it, so that reward is provably unspendable.
"""
from __future__ import annotations

from blockforge.consensus.params import ConsensusParams
from blockforge.consensus.pow import mine
from blockforge.consensus.rewards import block_subsidy
from blockforge.consensus.validation import BLOCK_VERSION
from blockforge.core import crypto
from blockforge.core.block import ZERO_HASH, Block
from blockforge.core.transaction import MAX_MEMO_LEN, Transaction

GENESIS_HEIGHT = 0
GENESIS_RECIPIENT = crypto.sha256d(b"BlockForge/genesis/unspendable")[:crypto.KEYHASH_LEN]


def build_genesis_block(params: ConsensusParams) -> Block:
    """Create and mine the genesis block for `params`."""
    coinbase = Transaction.create_coinbase(
        params,
        GENESIS_HEIGHT,
        GENESIS_RECIPIENT,
        block_subsidy(params, GENESIS_HEIGHT),
        params.genesis_message[:MAX_MEMO_LEN],
    )
    unmined = Block.build(
        version=BLOCK_VERSION,
        prev_hash=ZERO_HASH,
        timestamp=params.genesis_timestamp,
        bits=params.initial_bits,
        height=GENESIS_HEIGHT,
        transactions=[coinbase],
    )
    if params.genesis_nonce:
        candidate = unmined.with_nonce(params.genesis_nonce)
        if candidate.header.pow_valid():
            return candidate
    found = mine(unmined.header.prefix(), params.initial_bits)
    if found is None:
        raise RuntimeError("failed to mine genesis block")
    return unmined.with_nonce(found[0])


def is_genesis(block: Block) -> bool:
    """Structural check that a block sits in the genesis position."""
    h = block.header
    return h.height == GENESIS_HEIGHT and h.prev_hash == ZERO_HASH


def verify_genesis(block: Block, params: ConsensusParams) -> bool:
    """True if the block is a valid genesis for this network."""
    h = block.header
    return (
        is_genesis(block)
        and h.version == BLOCK_VERSION
        and h.timestamp == params.genesis_timestamp
        and h.bits == params.initial_bits
        and len(block.transactions) == 1
        and block.transactions[0].is_coinbase
        and block.merkle_root_valid()
        and h.pow_valid()
    )