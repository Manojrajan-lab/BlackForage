"""Block and header structures, canonical serialization, and Merkle root."""

import struct
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Sequence, Tuple

from blockforge.consensus.pow import NONCE_BYTES, header_hash, verify_pow
from blockforge.core.merkle import merkle_root

HASH_SIZE = 32
ZERO_HASH = b"\x00" * HASH_SIZE

# version, prev_hash, merkle_root, timestamp, bits, height (big-endian, fixed width)
_PREFIX = struct.Struct(">I32s32sQIQ")
HEADER_PREFIX_SIZE = _PREFIX.size  # 88
HEADER_SIZE = HEADER_PREFIX_SIZE + NONCE_BYTES  # 96

_U32 = struct.Struct(">I")
MAX_TX_COUNT_DECODE = 1_000_000  # sanity cap while decoding untrusted bytes


class BlockFormatError(ValueError):
    """Raised when block bytes or fields are malformed."""


@dataclass(frozen=True)
class BlockHeader:
    version: int
    prev_hash: bytes
    merkle_root: bytes
    timestamp: int
    bits: int
    height: int
    nonce: int = 0

    def __post_init__(self) -> None:
        if not 0 <= self.version <= 0xFFFFFFFF:
            raise BlockFormatError("version out of range")
        if len(self.prev_hash) != HASH_SIZE:
            raise BlockFormatError("prev_hash must be 32 bytes")
        if len(self.merkle_root) != HASH_SIZE:
            raise BlockFormatError("merkle_root must be 32 bytes")
        if not 0 <= self.timestamp <= 0xFFFFFFFFFFFFFFFF:
            raise BlockFormatError("timestamp out of range")
        if not 0 <= self.bits <= 0xFFFFFFFF:
            raise BlockFormatError("bits out of range")
        if not 0 <= self.height <= 0xFFFFFFFFFFFFFFFF:
            raise BlockFormatError("height out of range")
        if not 0 <= self.nonce < (1 << (8 * NONCE_BYTES)):
            raise BlockFormatError("nonce out of range")

    def prefix(self) -> bytes:
        """Header bytes excluding the nonce (what miners hash repeatedly)."""
        return _PREFIX.pack(
            self.version,
            self.prev_hash,
            self.merkle_root,
            self.timestamp,
            self.bits,
            self.height,
        )

    def serialize(self) -> bytes:
        return self.prefix() + self.nonce.to_bytes(NONCE_BYTES, "big")

    @classmethod
    def deserialize(cls, data: bytes) -> "BlockHeader":
        if len(data) != HEADER_SIZE:
            raise BlockFormatError("header must be %d bytes" % HEADER_SIZE)
        version, prev_hash, root, timestamp, bits, height = _PREFIX.unpack(
            data[:HEADER_PREFIX_SIZE]
        )
        nonce = int.from_bytes(data[HEADER_PREFIX_SIZE:], "big")
        return cls(version, prev_hash, root, timestamp, bits, height, nonce)

    def hash(self) -> bytes:
        return header_hash(self.prefix(), self.nonce)

    def hash_hex(self) -> str:
        return self.hash().hex()

    def with_nonce(self, nonce: int) -> "BlockHeader":
        return replace(self, nonce=nonce)

    def pow_valid(self) -> bool:
        return verify_pow(self.prefix(), self.nonce, self.bits)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "prev_hash": self.prev_hash.hex(),
            "merkle_root": self.merkle_root.hex(),
            "timestamp": self.timestamp,
            "bits": self.bits,
            "height": self.height,
            "nonce": self.nonce,
            "hash": self.hash_hex(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BlockHeader":
        try:
            return cls(
                version=int(d["version"]),
                prev_hash=bytes.fromhex(d["prev_hash"]),
                merkle_root=bytes.fromhex(d["merkle_root"]),
                timestamp=int(d["timestamp"]),
                bits=int(d["bits"]),
                height=int(d["height"]),
                nonce=int(d["nonce"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BlockFormatError("invalid header dict: %s" % exc) from exc


@dataclass(frozen=True)
class Block:
    """A header plus transactions.

    Transactions are any objects exposing `txid` (32 bytes) and `serialize()`.
    Decoding requires a tx_decoder(bytes) -> transaction supplied by the caller.
    """

    header: BlockHeader
    transactions: Tuple[Any, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "transactions", tuple(self.transactions))

    @property
    def hash(self) -> bytes:
        return self.header.hash()

    @property
    def hash_hex(self) -> str:
        return self.header.hash_hex()

    @property
    def height(self) -> int:
        return self.header.height

    @property
    def prev_hash(self) -> bytes:
        return self.header.prev_hash

    def txids(self) -> List[bytes]:
        return [tx.txid for tx in self.transactions]

    def compute_merkle_root(self) -> bytes:
        return merkle_root(self.txids())

    def merkle_root_valid(self) -> bool:
        if not self.transactions:
            return False
        return self.compute_merkle_root() == self.header.merkle_root

    @classmethod
    def build(
        cls,
        version: int,
        prev_hash: bytes,
        timestamp: int,
        bits: int,
        height: int,
        transactions: Sequence[Any],
        nonce: int = 0,
    ) -> "Block":
        """Create a block with the Merkle root computed from the transactions."""
        txs = tuple(transactions)
        root = merkle_root([tx.txid for tx in txs])
        header = BlockHeader(version, prev_hash, root, timestamp, bits, height, nonce)
        return cls(header, txs)

    def with_nonce(self, nonce: int) -> "Block":
        return Block(self.header.with_nonce(nonce), self.transactions)

    def serialize(self) -> bytes:
        parts = [self.header.serialize(), _U32.pack(len(self.transactions))]
        for tx in self.transactions:
            raw = tx.serialize()
            parts.append(_U32.pack(len(raw)))
            parts.append(raw)
        return b"".join(parts)

    @property
    def size(self) -> int:
        return len(self.serialize())

    @classmethod
    def deserialize(
        cls, data: bytes, tx_decoder: Callable[[bytes], Any]
    ) -> "Block":
        if len(data) < HEADER_SIZE + _U32.size:
            raise BlockFormatError("block too short")
        header = BlockHeader.deserialize(data[:HEADER_SIZE])
        offset = HEADER_SIZE
        (count,) = _U32.unpack_from(data, offset)
        offset += _U32.size
        if count > MAX_TX_COUNT_DECODE:
            raise BlockFormatError("transaction count too large")
        txs = []
        for _ in range(count):
            if offset + _U32.size > len(data):
                raise BlockFormatError("truncated transaction length")
            (length,) = _U32.unpack_from(data, offset)
            offset += _U32.size
            end = offset + length
            if end > len(data):
                raise BlockFormatError("truncated transaction")
            try:
                txs.append(tx_decoder(data[offset:end]))
            except BlockFormatError:
                raise
            except Exception as exc:
                raise BlockFormatError("invalid transaction: %s" % exc) from exc
            offset = end
        if offset != len(data):
            raise BlockFormatError("trailing bytes after block")
        return cls(header, tuple(txs))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "header": self.header.to_dict(),
            "transactions": [tx.serialize().hex() for tx in self.transactions],
            "size": self.size,
        }

    @classmethod
    def from_dict(
        cls, d: Dict[str, Any], tx_decoder: Callable[[bytes], Any]
    ) -> "Block":
        try:
            header = BlockHeader.from_dict(d["header"])
            txs = tuple(tx_decoder(bytes.fromhex(h)) for h in d["transactions"])
        except BlockFormatError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise BlockFormatError("invalid block dict: %s" % exc) from exc
        return cls(header, txs)