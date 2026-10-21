"""Transactions for BlockForge (account model).

Canonical layout (see core/serialization.py), signature excluded from the
signing body:

    u8   version
    u8   kind            0 = coinbase, 1 = transfer
    u32  chain_id        replay protection across networks
    var  sender_pubkey   33-byte compressed key (empty for coinbase)
    20B  recipient       key hash (see crypto.pubkey_hash)
    u64  amount          base units
    u64  fee             base units (0 for coinbase)
    u64  nonce           transfer: sender's account nonce; coinbase: block height
    var  memo            <= MAX_MEMO_LEN bytes
    var  signature       64-byte canonical low-S (empty for coinbase)

signing_hash = SHA-256d(SIGNING_DOMAIN || body_without_signature)
txid         = SHA-256d(full serialization)

Replay protection:
  * chain_id is inside the signed body -> a tx is invalid on any other network.
  * nonce must equal the sender's current account nonce (checked by the ledger),
    so a confirmed tx can never be applied twice.
Coinbase txids are unique because nonce = block height.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cached_property
from typing import Optional

from blockforge.consensus.params import ConsensusParams
from blockforge.core import crypto
from blockforge.core.serialization import Reader, SerializationError, Writer

TX_VERSION = 1
KIND_COINBASE = 0
KIND_TRANSFER = 1
MAX_MEMO_LEN = 100
# SQLite integers are signed 64-bit; keep nonces far from the limit.
MAX_NONCE = 1 << 62
SIGNING_DOMAIN = b"BlockForge/tx/v1"

_HEX_CHARS = frozenset("0123456789abcdef")


class TransactionError(ValueError):
    """Raised for malformed or invalid transactions."""


@dataclass(frozen=True)
class Transaction:
    version: int
    kind: int
    chain_id: int
    sender_pubkey: bytes
    recipient: bytes
    amount: int
    fee: int
    nonce: int
    memo: bytes
    signature: bytes

    # ------------------------------------------------------------ properties
    @property
    def is_coinbase(self) -> bool:
        return self.kind == KIND_COINBASE

    @property
    def sender_key_hash(self) -> Optional[bytes]:
        """20-byte sender identity, or None for coinbase."""
        if self.is_coinbase:
            return None
        return crypto.pubkey_hash(self.sender_pubkey)

    # --------------------------------------------------------- serialization
    def _body(self, w: Writer) -> Writer:
        return (
            w.u8(self.version)
            .u8(self.kind)
            .u32(self.chain_id)
            .var_bytes(self.sender_pubkey, crypto.PUBKEY_LEN)
            .fixed(self.recipient, crypto.KEYHASH_LEN)
            .u64(self.amount)
            .u64(self.fee)
            .u64(self.nonce)
            .var_bytes(self.memo, MAX_MEMO_LEN)
        )

    def serialize_unsigned(self) -> bytes:
        try:
            return self._body(Writer()).getvalue()
        except SerializationError as exc:
            raise TransactionError(str(exc)) from exc

    def serialize(self) -> bytes:
        try:
            w = self._body(Writer())
            w.var_bytes(self.signature, crypto.SIG_LEN)
            return w.getvalue()
        except SerializationError as exc:
            raise TransactionError(str(exc)) from exc

    @classmethod
    def deserialize(cls, data: bytes) -> "Transaction":
        """Strictly decode one transaction; trailing bytes are rejected."""
        try:
            r = Reader(data)
            version = r.u8()
            kind = r.u8()
            chain_id = r.u32()
            sender_pubkey = r.var_bytes(crypto.PUBKEY_LEN)
            recipient = r.fixed(crypto.KEYHASH_LEN)
            amount = r.u64()
            fee = r.u64()
            nonce = r.u64()
            memo = r.var_bytes(MAX_MEMO_LEN)
            signature = r.var_bytes(crypto.SIG_LEN)
            r.finish()
        except SerializationError as exc:
            raise TransactionError(f"malformed transaction: {exc}") from exc
        return cls(version, kind, chain_id, sender_pubkey, recipient,
                   amount, fee, nonce, memo, signature)

    def to_hex(self) -> str:
        return self.serialize().hex()

    @classmethod
    def from_hex(cls, text: str) -> "Transaction":
        if not isinstance(text, str) or not set(text) <= _HEX_CHARS or len(text) % 2:
            raise TransactionError("transaction hex must be lowercase hex")
        return cls.deserialize(bytes.fromhex(text))

    # ---------------------------------------------------------------- hashes
    def signing_hash(self) -> bytes:
        return crypto.sha256d(SIGNING_DOMAIN + self.serialize_unsigned())

    @cached_property
    def txid(self) -> bytes:
        """32-byte transaction ID (commits to the signature)."""
        return crypto.sha256d(self.serialize())

    @property
    def txid_hex(self) -> str:
        return self.txid.hex()

    @property
    def size(self) -> int:
        return len(self.serialize())

    # ---------------------------------------------------------- construction
    @classmethod
    def create_transfer(
        cls,
        secret: bytes,
        params: ConsensusParams,
        recipient: bytes,
        amount: int,
        fee: int,
        nonce: int,
        memo: bytes = b"",
    ) -> "Transaction":
        """Build and sign a transfer. Does not check balances."""
        unsigned = cls(
            version=TX_VERSION,
            kind=KIND_TRANSFER,
            chain_id=params.chain_id,
            sender_pubkey=crypto.private_to_public(secret),
            recipient=recipient,
            amount=amount,
            fee=fee,
            nonce=nonce,
            memo=memo,
            signature=b"",
        )
        try:
            sig = crypto.sign(secret, unsigned.signing_hash())
        except crypto.CryptoError as exc:
            raise TransactionError(str(exc)) from exc
        return replace(unsigned, signature=sig)

    @classmethod
    def create_coinbase(
        cls,
        params: ConsensusParams,
        height: int,
        recipient: bytes,
        amount: int,
        extra: bytes = b"",
    ) -> "Transaction":
        """Build a coinbase paying subsidy + fees. `amount` is verified by block validation."""
        return cls(
            version=TX_VERSION,
            kind=KIND_COINBASE,
            chain_id=params.chain_id,
            sender_pubkey=b"",
            recipient=recipient,
            amount=amount,
            fee=0,
            nonce=height,
            memo=extra,
            signature=b"",
        )

    # ------------------------------------------------------------ validation
    def validate_stateless(self, params: ConsensusParams) -> None:
        """Checks that need no chain state. Raises TransactionError on failure.

        Does NOT check balance, account nonce, or coinbase amount/height; the
        ledger and block validator do that.
        """
        if self.version != TX_VERSION:
            raise TransactionError("unsupported transaction version")
        if self.chain_id != params.chain_id:
            raise TransactionError("wrong chain_id")
        if len(self.memo) > MAX_MEMO_LEN:
            raise TransactionError("memo too long")
        if self.amount > params.max_supply or self.fee > params.max_supply:
            raise TransactionError("amount or fee exceeds max supply")
        if self.nonce >= MAX_NONCE:
            raise TransactionError("nonce out of range")
        if len(self.recipient) != crypto.KEYHASH_LEN:
            raise TransactionError("bad recipient")

        if self.kind == KIND_COINBASE:
            if self.sender_pubkey or self.signature:
                raise TransactionError("coinbase must be unsigned with no sender")
            if self.fee != 0:
                raise TransactionError("coinbase fee must be 0")
        elif self.kind == KIND_TRANSFER:
            if self.amount <= 0:
                raise TransactionError("amount must be positive")
            if self.fee < params.min_fee:
                raise TransactionError("fee below minimum")
            if not crypto.is_valid_public_key(self.sender_pubkey):
                raise TransactionError("invalid sender public key")
            if not crypto.is_canonical_signature(self.signature):
                raise TransactionError("non-canonical signature")
            if not crypto.verify(self.sender_pubkey, self.signing_hash(), self.signature):
                raise TransactionError("invalid signature")
        else:
            raise TransactionError("unknown transaction kind")

        if self.size > params.max_tx_bytes:
            raise TransactionError("transaction too large")