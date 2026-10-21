"""P2P wire protocol for BlockForge.

Frame (big-endian, all fields fixed width):

    4B   magic       derived from chain_id, so nodes on other networks are rejected at once
    12B  command     ASCII, NUL padded
    u32  length      payload length, bounded by MAX_PAYLOAD
    4B   checksum    first 4 bytes of SHA-256d(payload)
    ...  payload     canonical encoding from core/serialization.py

Every decoder is strict: bounded lengths, exact consumption, no trailing bytes.
Payload bytes for blocks and transactions are carried raw and decoded by the
caller with Block.deserialize / Transaction.deserialize.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Dict, List, Tuple, Type

from blockforge.core import crypto
from blockforge.core.block import Block
from blockforge.core.serialization import Reader, SerializationError, Writer
from blockforge.core.transaction import Transaction

PROTOCOL_VERSION = 1
MAGIC_LEN = 4
COMMAND_LEN = 12
CHECKSUM_LEN = 4
HEADER_LEN = MAGIC_LEN + COMMAND_LEN + 4 + CHECKSUM_LEN  # 24

MAX_PAYLOAD = 2_000_000          # hard cap on any frame payload
MAX_INV_ITEMS = 500
MAX_LOCATOR = 64
MAX_ADDRS = 100
MAX_USER_AGENT = 64
MAX_REJECT_REASON = 120
MAX_HOST_LEN = 45                # longest textual IPv6 address

INV_TX = 1
INV_BLOCK = 2
ZERO_HASH = b"\x00" * 32


class MessageError(ValueError):
    """Raised for any malformed, oversized or unknown message."""


def network_magic(chain_id: int) -> bytes:
    """4-byte network identifier derived from the chain id."""
    return crypto.sha256(b"BlockForge/magic" + chain_id.to_bytes(4, "big"))[:MAGIC_LEN]


def _checksum(payload: bytes) -> bytes:
    return crypto.sha256d(payload)[:CHECKSUM_LEN]


# ------------------------------------------------------------------ messages
class Message:
    command: ClassVar[str]

    def encode_payload(self) -> bytes:
        return b""

    @classmethod
    def decode_payload(cls, data: bytes) -> "Message":
        if data:
            raise MessageError(f"{cls.command}: unexpected payload")
        return cls()


@dataclass(frozen=True)
class Version(Message):
    command: ClassVar[str] = "version"
    protocol_version: int
    chain_id: int
    timestamp: int
    nonce: int            # random per connection; detects connections to ourselves
    listen_port: int      # 0 = not accepting inbound connections
    height: int
    tip_hash: bytes
    user_agent: bytes

    def encode_payload(self) -> bytes:
        return (
            Writer().u32(self.protocol_version).u32(self.chain_id).u64(self.timestamp)
            .u64(self.nonce).u16(self.listen_port).u64(self.height)
            .fixed(self.tip_hash, 32).var_bytes(self.user_agent, MAX_USER_AGENT)
            .getvalue()
        )

    @classmethod
    def decode_payload(cls, data: bytes) -> "Version":
        r = Reader(data)
        msg = cls(r.u32(), r.u32(), r.u64(), r.u64(), r.u16(), r.u64(),
                  r.fixed(32), r.var_bytes(MAX_USER_AGENT))
        r.finish()
        return msg


@dataclass(frozen=True)
class Verack(Message):
    command: ClassVar[str] = "verack"


@dataclass(frozen=True)
class Ping(Message):
    command: ClassVar[str] = "ping"
    nonce: int

    def encode_payload(self) -> bytes:
        return Writer().u64(self.nonce).getvalue()

    @classmethod
    def decode_payload(cls, data: bytes) -> "Ping":
        r = Reader(data)
        msg = cls(r.u64())
        r.finish()
        return msg


@dataclass(frozen=True)
class Pong(Ping):
    command: ClassVar[str] = "pong"


@dataclass(frozen=True)
class GetAddr(Message):
    command: ClassVar[str] = "getaddr"


@dataclass(frozen=True)
class Addr(Message):
    command: ClassVar[str] = "addr"
    addrs: Tuple[Tuple[str, int, int], ...] = field(default_factory=tuple)  # (host, port, last_seen)

    def encode_payload(self) -> bytes:
        if len(self.addrs) > MAX_ADDRS:
            raise MessageError("too many addresses")
        w = Writer().u16(len(self.addrs))
        for host, port, seen in self.addrs:
            try:
                w.var_bytes(host.encode("ascii"), MAX_HOST_LEN).u16(port).u64(seen)
            except (UnicodeEncodeError, SerializationError) as exc:
                raise MessageError(f"bad address entry: {exc}") from exc
        return w.getvalue()

    @classmethod
    def decode_payload(cls, data: bytes) -> "Addr":
        r = Reader(data)
        count = r.u16()
        if count > MAX_ADDRS:
            raise MessageError("too many addresses")
        out = []
        for _ in range(count):
            raw = r.var_bytes(MAX_HOST_LEN)
            try:
                host = raw.decode("ascii")
            except UnicodeDecodeError as exc:
                raise MessageError("non-ascii host") from exc
            out.append((host, r.u16(), r.u64()))
        r.finish()
        return cls(tuple(out))


@dataclass(frozen=True)
class Inv(Message):
    """Announces objects the sender has: [(INV_TX | INV_BLOCK, 32-byte hash)]."""
    command: ClassVar[str] = "inv"
    items: Tuple[Tuple[int, bytes], ...] = field(default_factory=tuple)

    def encode_payload(self) -> bytes:
        if len(self.items) > MAX_INV_ITEMS:
            raise MessageError("too many inventory items")
        w = Writer().u16(len(self.items))
        for kind, h in self.items:
            if kind not in (INV_TX, INV_BLOCK):
                raise MessageError("bad inventory type")
            w.u8(kind).fixed(h, 32)
        return w.getvalue()

    @classmethod
    def decode_payload(cls, data: bytes) -> "Inv":
        r = Reader(data)
        count = r.u16()
        if count > MAX_INV_ITEMS:
            raise MessageError("too many inventory items")
        items = []
        for _ in range(count):
            kind = r.u8()
            if kind not in (INV_TX, INV_BLOCK):
                raise MessageError("bad inventory type")
            items.append((kind, r.fixed(32)))
        r.finish()
        return cls(tuple(items))


@dataclass(frozen=True)
class GetData(Inv):
    """Requests the full objects for the listed inventory items."""
    command: ClassVar[str] = "getdata"


@dataclass(frozen=True)
class NotFound(Inv):
    """Reply to GetData for items the sender no longer has."""
    command: ClassVar[str] = "notfound"


@dataclass(frozen=True)
class GetBlocks(Message):
    """Ask for block hashes after the newest locator entry we share (see ForkChoice.block_locator)."""
    command: ClassVar[str] = "getblocks"
    locator: Tuple[bytes, ...] = field(default_factory=tuple)
    stop_hash: bytes = ZERO_HASH

    def encode_payload(self) -> bytes:
        if not 1 <= len(self.locator) <= MAX_LOCATOR:
            raise MessageError("bad locator size")
        w = Writer().u8(len(self.locator))
        for h in self.locator:
            w.fixed(h, 32)
        return w.fixed(self.stop_hash, 32).getvalue()

    @classmethod
    def decode_payload(cls, data: bytes) -> "GetBlocks":
        r = Reader(data)
        count = r.u8()
        if not 1 <= count <= MAX_LOCATOR:
            raise MessageError("bad locator size")
        locator = tuple(r.fixed(32) for _ in range(count))
        msg = cls(locator, r.fixed(32))
        r.finish()
        return msg


@dataclass(frozen=True)
class BlockMsg(Message):
    command: ClassVar[str] = "block"
    raw: bytes

    def encode_payload(self) -> bytes:
        return self.raw

    @classmethod
    def decode_payload(cls, data: bytes) -> "BlockMsg":
        if not data:
            raise MessageError("empty block")
        return cls(data)

    @classmethod
    def from_block(cls, block: Block) -> "BlockMsg":
        return cls(block.serialize())

    def to_block(self) -> Block:
        try:
            return Block.deserialize(self.raw, Transaction.deserialize)
        except ValueError as exc:
            raise MessageError(f"bad block: {exc}") from exc


@dataclass(frozen=True)
class TxMsg(Message):
    command: ClassVar[str] = "tx"
    raw: bytes

    def encode_payload(self) -> bytes:
        return self.raw

    @classmethod
    def decode_payload(cls, data: bytes) -> "TxMsg":
        if not data:
            raise MessageError("empty transaction")
        return cls(data)

    @classmethod
    def from_tx(cls, tx: Transaction) -> "TxMsg":
        return cls(tx.serialize())

    def to_tx(self) -> Transaction:
        try:
            return Transaction.deserialize(self.raw)
        except ValueError as exc:
            raise MessageError(f"bad transaction: {exc}") from exc


@dataclass(frozen=True)
class Reject(Message):
    command: ClassVar[str] = "reject"
    rejected_command: bytes   # ASCII command being rejected
    code: int                 # see REJECT_* below
    reason: bytes

    def encode_payload(self) -> bytes:
        return (Writer().var_bytes(self.rejected_command, COMMAND_LEN).u8(self.code)
                .var_bytes(self.reason, MAX_REJECT_REASON).getvalue())

    @classmethod
    def decode_payload(cls, data: bytes) -> "Reject":
        r = Reader(data)
        msg = cls(r.var_bytes(COMMAND_LEN), r.u8(), r.var_bytes(MAX_REJECT_REASON))
        r.finish()
        return msg


REJECT_MALFORMED = 1
REJECT_INVALID = 2
REJECT_DUPLICATE = 3
REJECT_OBSOLETE = 4

_REGISTRY: Dict[str, Type[Message]] = {
    cls.command: cls
    for cls in (Version, Verack, Ping, Pong, GetAddr, Addr, Inv, GetData, NotFound,
                GetBlocks, BlockMsg, TxMsg, Reject)
}


# -------------------------------------------------------------------- framing
def encode_message(magic: bytes, msg: Message) -> bytes:
    """Serialize a message into a complete frame."""
    payload = msg.encode_payload()
    if len(payload) > MAX_PAYLOAD:
        raise MessageError("payload too large")
    command = msg.command.encode("ascii").ljust(COMMAND_LEN, b"\x00")
    return (magic + command + len(payload).to_bytes(4, "big")
            + _checksum(payload) + payload)


def parse_header(magic: bytes, header: bytes) -> Tuple[str, int, bytes]:
    """Validate a 24-byte header. Returns (command, payload_length, checksum)."""
    if len(header) != HEADER_LEN:
        raise MessageError("short header")
    if header[:MAGIC_LEN] != magic:
        raise MessageError("wrong network magic")
    raw = header[MAGIC_LEN:MAGIC_LEN + COMMAND_LEN]
    name, _, padding = raw.partition(b"\x00")
    if padding.strip(b"\x00"):
        raise MessageError("non-canonical command padding")
    try:
        command = name.decode("ascii")
    except UnicodeDecodeError as exc:
        raise MessageError("non-ascii command") from exc
    if command not in _REGISTRY:
        raise MessageError(f"unknown command {command!r}")
    length = int.from_bytes(header[MAGIC_LEN + COMMAND_LEN:MAGIC_LEN + COMMAND_LEN + 4], "big")
    if length > MAX_PAYLOAD:
        raise MessageError("payload too large")
    return command, length, header[-CHECKSUM_LEN:]


def decode_payload(command: str, checksum: bytes, payload: bytes) -> Message:
    """Verify the checksum and strictly decode the payload."""
    if _checksum(payload) != checksum:
        raise MessageError("bad checksum")
    cls = _REGISTRY.get(command)
    if cls is None:
        raise MessageError(f"unknown command {command!r}")
    try:
        return cls.decode_payload(payload)
    except SerializationError as exc:
        raise MessageError(f"{command}: {exc}") from exc