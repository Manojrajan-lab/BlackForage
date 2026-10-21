"""Proof-of-Work primitives: compact targets, double-SHA256 header hashing, nonce search."""

import hashlib
import threading
from typing import Optional, Tuple

NONCE_BYTES = 8
MAX_NONCE = (1 << (8 * NONCE_BYTES)) - 1

# Easiest allowed target (compact form). Difficulty can never go below this.
POW_LIMIT_BITS = 0x2000FFFF


def bits_to_target(bits: int) -> int:
    """Decode compact 'bits' into a 256-bit integer target."""
    if not 0 <= bits <= 0xFFFFFFFF:
        raise ValueError("bits out of range")
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    if bits & 0x00800000:
        raise ValueError("negative target not allowed")
    if exponent <= 3:
        target = mantissa >> (8 * (3 - exponent))
    else:
        target = mantissa << (8 * (exponent - 3))
    if target <= 0 or target >= (1 << 256):
        raise ValueError("target out of range")
    return target


def target_to_bits(target: int) -> int:
    """Encode an integer target into compact 'bits'."""
    if target <= 0 or target >= (1 << 256):
        raise ValueError("target out of range")
    size = (target.bit_length() + 7) // 8
    if size <= 3:
        compact = target << (8 * (3 - size))
    else:
        compact = target >> (8 * (size - 3))
    if compact & 0x00800000:
        compact >>= 8
        size += 1
    return compact | (size << 24)


POW_LIMIT = bits_to_target(POW_LIMIT_BITS)


def is_valid_bits(bits: int) -> bool:
    """True if bits decodes to a target within the allowed range."""
    try:
        return bits_to_target(bits) <= POW_LIMIT
    except ValueError:
        return False


def work_from_bits(bits: int) -> int:
    """Expected number of hashes for this target (used for chain work)."""
    return (1 << 256) // (bits_to_target(bits) + 1)


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def header_hash(header_prefix: bytes, nonce: int) -> bytes:
    """Hash of header_prefix || nonce (8 bytes, big-endian)."""
    if not 0 <= nonce <= MAX_NONCE:
        raise ValueError("nonce out of range")
    return sha256d(header_prefix + nonce.to_bytes(NONCE_BYTES, "big"))


def hash_meets_target(block_hash: bytes, bits: int) -> bool:
    """True if the hash, read as a big-endian integer, is <= target."""
    if not is_valid_bits(bits):
        return False
    return int.from_bytes(block_hash, "big") <= bits_to_target(bits)


def verify_pow(header_prefix: bytes, nonce: int, bits: int) -> bool:
    """Recompute the header hash and check it against the target."""
    try:
        return hash_meets_target(header_hash(header_prefix, nonce), bits)
    except ValueError:
        return False


def mine(
    header_prefix: bytes,
    bits: int,
    start_nonce: int = 0,
    max_nonce: int = MAX_NONCE,
    stop_event: Optional[threading.Event] = None,
    check_every: int = 4096,
) -> Optional[Tuple[int, bytes]]:
    """Search for a nonce satisfying the target.

    Returns (nonce, block_hash) on success, or None if the range is exhausted
    or stop_event is set (e.g. a new block arrived from a peer).
    """
    if not is_valid_bits(bits):
        raise ValueError("invalid bits")
    if not 0 <= start_nonce <= max_nonce <= MAX_NONCE:
        raise ValueError("invalid nonce range")

    target = bits_to_target(bits)
    base = hashlib.sha256()
    base.update(header_prefix)

    nonce = start_nonce
    while nonce <= max_nonce:
        if stop_event is not None and nonce % check_every == 0 and stop_event.is_set():
            return None
        h = base.copy()
        h.update(nonce.to_bytes(NONCE_BYTES, "big"))
        digest = hashlib.sha256(h.digest()).digest()
        if int.from_bytes(digest, "big") <= target:
            return nonce, digest
        nonce += 1
    return None