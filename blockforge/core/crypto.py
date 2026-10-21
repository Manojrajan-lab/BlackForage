"""Cryptographic utilities for BlockForge.

Primitives (all established; nothing custom):
  * SHA-256 / double SHA-256 (hashlib)
  * ECDSA over secp256k1 with RFC6979 deterministic nonces (libsecp256k1 via coincurve)

Consensus-critical canonical-form rules enforced here:
  * Public keys are 33-byte compressed points, validated as on-curve.
  * Signatures are exactly 64 bytes (r || s), with 1 <= r,s < N and LOW-S only
    (s <= N/2). This removes ECDSA signature malleability, so a third party
    cannot alter a transaction's signature (and thus its ID).
  * Addresses are "<prefix><hex(20-byte key hash || 4-byte checksum)>",
    lowercase hex only.

Never log or return private keys from this module.
"""
from __future__ import annotations

import hashlib

from coincurve import PrivateKey, PublicKey

HASH_LEN = 32
PUBKEY_LEN = 33
PRIVKEY_LEN = 32
SIG_LEN = 64
KEYHASH_LEN = 20
CHECKSUM_LEN = 4

# secp256k1 group order
SECP256K1_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_HALF_N = SECP256K1_N // 2

_HEX_CHARS = frozenset("0123456789abcdef")


class CryptoError(ValueError):
    """Raised on invalid keys, signatures or addresses."""


# --------------------------------------------------------------------- hashing
def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256d(data: bytes) -> bytes:
    """Double SHA-256 (used for block hashes, Merkle nodes and checksums)."""
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


# ------------------------------------------------------------------------ keys
def generate_private_key() -> bytes:
    """Return a fresh 32-byte secret from the OS CSPRNG (validated by libsecp256k1)."""
    return PrivateKey().secret


def _load_private(secret: bytes) -> PrivateKey:
    if not isinstance(secret, (bytes, bytearray)) or len(secret) != PRIVKEY_LEN:
        raise CryptoError("private key must be 32 bytes")
    try:
        return PrivateKey(bytes(secret))
    except Exception as exc:  # coincurve raises ValueError for out-of-range secrets
        raise CryptoError("invalid private key") from exc


def private_to_public(secret: bytes) -> bytes:
    """Derive the 33-byte compressed public key."""
    return _load_private(secret).public_key.format(compressed=True)


def is_valid_public_key(pubkey: bytes) -> bool:
    """True iff pubkey is a 33-byte compressed encoding of a valid curve point."""
    if not isinstance(pubkey, (bytes, bytearray)) or len(pubkey) != PUBKEY_LEN:
        return False
    if pubkey[0] not in (0x02, 0x03):
        return False
    try:
        PublicKey(bytes(pubkey))
    except Exception:
        return False
    return True


# ------------------------------------------------------------------ signatures
def _der_int(value: int) -> bytes:
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return b"\x02" + bytes([len(raw)]) + raw


def _compact_to_der(sig: bytes) -> bytes:
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    body = _der_int(r) + _der_int(s)
    return b"\x30" + bytes([len(body)]) + body  # body < 128 bytes, single-byte length


def is_canonical_signature(sig: bytes) -> bool:
    """64 bytes, 1 <= r,s < N, and low-S."""
    if not isinstance(sig, (bytes, bytearray)) or len(sig) != SIG_LEN:
        return False
    r = int.from_bytes(sig[:32], "big")
    s = int.from_bytes(sig[32:], "big")
    return 1 <= r < SECP256K1_N and 1 <= s <= _HALF_N


def sign(secret: bytes, msg_hash: bytes) -> bytes:
    """Sign a 32-byte message hash. Returns canonical 64-byte (r || s), low-S.

    The caller hashes the message (see Transaction.signing_hash); this function
    never hashes internally, so the signed digest is unambiguous.
    """
    if not isinstance(msg_hash, (bytes, bytearray)) or len(msg_hash) != HASH_LEN:
        raise CryptoError("message hash must be 32 bytes")
    key = _load_private(secret)
    # sign_recoverable returns 65 bytes: r(32) || s(32) || recid(1); libsecp256k1
    # always emits low-S and uses RFC6979 deterministic nonces.
    sig = key.sign_recoverable(bytes(msg_hash), hasher=None)[:SIG_LEN]
    if not is_canonical_signature(sig):  # defensive; should be unreachable
        raise CryptoError("produced non-canonical signature")
    return sig


def verify(pubkey: bytes, msg_hash: bytes, sig: bytes) -> bool:
    """Verify a canonical signature. Returns False (never raises) on any invalid input."""
    if not isinstance(msg_hash, (bytes, bytearray)) or len(msg_hash) != HASH_LEN:
        return False
    if not is_canonical_signature(sig):
        return False
    if not is_valid_public_key(pubkey):
        return False
    try:
        return bool(
            PublicKey(bytes(pubkey)).verify(
                _compact_to_der(bytes(sig)), bytes(msg_hash), hasher=None
            )
        )
    except Exception:
        return False


# ------------------------------------------------------------------- addresses
def pubkey_hash(pubkey: bytes) -> bytes:
    """20-byte key hash: first 20 bytes of SHA-256d(pubkey)."""
    if not is_valid_public_key(pubkey):
        raise CryptoError("invalid public key")
    return sha256d(bytes(pubkey))[:KEYHASH_LEN]


def _checksum(prefix: str, key_hash: bytes) -> bytes:
    return sha256d(prefix.encode("ascii") + key_hash)[:CHECKSUM_LEN]


def key_hash_to_address(key_hash: bytes, prefix: str) -> str:
    if len(key_hash) != KEYHASH_LEN:
        raise CryptoError("key hash must be 20 bytes")
    return prefix + (key_hash + _checksum(prefix, key_hash)).hex()


def pubkey_to_address(pubkey: bytes, prefix: str) -> str:
    return key_hash_to_address(pubkey_hash(pubkey), prefix)


def address_to_key_hash(address: str, prefix: str) -> bytes:
    """Decode and checksum-verify an address; return the 20-byte key hash."""
    if not isinstance(address, str) or not address.startswith(prefix):
        raise CryptoError("bad address prefix")
    body = address[len(prefix):]
    if len(body) != 2 * (KEYHASH_LEN + CHECKSUM_LEN) or not set(body) <= _HEX_CHARS:
        raise CryptoError("malformed address")
    raw = bytes.fromhex(body)
    key_hash, checksum = raw[:KEYHASH_LEN], raw[KEYHASH_LEN:]
    if checksum != _checksum(prefix, key_hash):
        raise CryptoError("address checksum mismatch")
    return key_hash


def is_valid_address(address: str, prefix: str) -> bool:
    try:
        address_to_key_hash(address, prefix)
    except CryptoError:
        return False
    return True