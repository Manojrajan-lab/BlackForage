"""Merkle tree over transaction IDs.

Consensus rules:
  * Leaves are 32-byte txids. Interior node = SHA-256d(0x01 || left || right);
    leaf = SHA-256d(0x00 || txid). The prefixes domain-separate leaves from
    interior nodes (blocks second-preimage attacks).
  * An odd node at any level is promoted unchanged to the next level (it is
    NOT duplicated), which avoids the duplicate-leaf mutation problem
    (CVE-2012-2459).
  * Empty trees are invalid; a block always has at least a coinbase.
"""
from __future__ import annotations

from typing import List, Sequence

from blockforge.core import crypto

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


class MerkleError(ValueError):
    """Raised for invalid Merkle inputs."""


def _leaf(txid: bytes) -> bytes:
    if not isinstance(txid, (bytes, bytearray)) or len(txid) != crypto.HASH_LEN:
        raise MerkleError("txid must be 32 bytes")
    return crypto.sha256d(LEAF_PREFIX + bytes(txid))


def _node(left: bytes, right: bytes) -> bytes:
    return crypto.sha256d(NODE_PREFIX + left + right)


def merkle_root(txids: Sequence[bytes]) -> bytes:
    """Compute the Merkle root of an ordered, non-empty list of txids."""
    if len(txids) == 0:
        raise MerkleError("cannot build a Merkle tree with no transactions")
    level: List[bytes] = [_leaf(t) for t in txids]
    while len(level) > 1:
        nxt: List[bytes] = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_node(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])  # promote odd node
        level = nxt
    return level[0]


def merkle_proof(txids: Sequence[bytes], index: int) -> List[tuple]:
    """Return a proof for txids[index] as a list of (sibling_hash, sibling_is_left)."""
    if not 0 <= index < len(txids):
        raise MerkleError("index out of range")
    level: List[bytes] = [_leaf(t) for t in txids]
    proof: List[tuple] = []
    idx = index
    while len(level) > 1:
        if idx % 2 == 1:
            proof.append((level[idx - 1], True))
        elif idx + 1 < len(level):
            proof.append((level[idx + 1], False))
        # else: promoted odd node, no sibling at this level
        nxt: List[bytes] = []
        for i in range(0, len(level) - 1, 2):
            nxt.append(_node(level[i], level[i + 1]))
        if len(level) % 2 == 1:
            nxt.append(level[-1])
        level = nxt
        idx //= 2
    return proof


def verify_proof(txid: bytes, proof: Sequence[tuple], root: bytes) -> bool:
    """Verify a Merkle proof produced by merkle_proof. Never raises."""
    try:
        h = _leaf(txid)
        for sibling, sibling_is_left in proof:
            if not isinstance(sibling, (bytes, bytearray)) or len(sibling) != crypto.HASH_LEN:
                return False
            h = _node(bytes(sibling), h) if sibling_is_left else _node(h, bytes(sibling))
        return h == root
    except MerkleError:
        return False