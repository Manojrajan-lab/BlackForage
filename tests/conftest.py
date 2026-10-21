"""Shared fixtures. Everything uses REAL proof-of-work on the DEV network
(tiny difficulty) and real SQLite files; nothing is mocked or simulated."""
from __future__ import annotations

import os
from typing import Iterable, Optional

import pytest

from blockforge.consensus.params import DEV, ConsensusParams
from blockforge.consensus.pow import mine
from blockforge.consensus.rewards import block_subsidy
from blockforge.consensus.validation import BLOCK_VERSION
from blockforge.core import crypto
from blockforge.core.block import Block
from blockforge.core.transaction import Transaction
from blockforge.node.node import Node
from blockforge.wallet.wallet import Wallet


@pytest.fixture
def params() -> ConsensusParams:
    return DEV


@pytest.fixture
def make_node(tmp_path):
    nodes = []

    def factory(name: str = "node.db") -> Node:
        node = Node(DEV, os.path.join(str(tmp_path), name))
        node.start()
        nodes.append(node)
        return node

    yield factory
    for node in nodes:
        try:
            node.stop()
        except Exception:
            pass


@pytest.fixture
def node(make_node) -> Node:
    return make_node()


@pytest.fixture
def alice() -> Wallet:
    return Wallet.generate(DEV)


@pytest.fixture
def bob() -> Wallet:
    return Wallet.generate(DEV)


def solve(block: Block) -> Block:
    nonce, _ = mine(block.header.prefix(), block.header.bits)
    return block.with_nonce(nonce)


def mine_next(node: Node, key_hash: bytes) -> Block:
    """Mine one block on top of the node's tip and submit it."""
    block = solve(node.build_template(key_hash))
    node.submit_block(block)
    return block


def mine_blocks(node: Node, key_hash: bytes, count: int) -> list:
    return [mine_next(node, key_hash) for _ in range(count)]


def make_block_on(node: Node, parent_hash: bytes, key_hash: bytes,
                  txs: Iterable[Transaction] = (), extra: bytes = b"fork",
                  timestamp: Optional[int] = None, fees: Optional[int] = None) -> Block:
    """Build and solve a block on ANY stored parent (used to create forks)."""
    parent = node.get_block_by_hash(parent_hash)
    height = parent.height + 1
    txs = list(txs)
    total_fees = sum(t.fee for t in txs) if fees is None else fees
    bits = node.fork_choice.required_bits_for_child(parent_hash)
    ts = timestamp or max(parent.header.timestamp + 1,
                          node.fork_choice.mtp_of(parent_hash) + 1)
    coinbase = Transaction.create_coinbase(
        DEV, height, key_hash, block_subsidy(DEV, height) + total_fees, extra)
    return solve(Block.build(BLOCK_VERSION, parent_hash, ts, bits, height, [coinbase, *txs]))


@pytest.fixture
def helpers():
    class H:
        solve = staticmethod(solve)
        mine_next = staticmethod(mine_next)
        mine_blocks = staticmethod(mine_blocks)
        make_block_on = staticmethod(make_block_on)
    return H