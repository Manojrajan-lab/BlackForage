"""One P2P connection: framing, handshake, keepalive, rate limits and ban score.

Lifecycle (driven by network/p2p.py):
    peer = Peer(reader, writer, magic, chain_id, outbound, address, local_nonce)
    await peer.handshake(our_version)       # version / verack exchange
    await peer.run(handler)                 # until the connection closes

Before the handshake completes, only Version and Verack are accepted. After it,
Ping/Pong are handled here and everything else goes to `handler(peer, msg)`.
Malformed frames disconnect immediately; other misbehaviour accumulates a
ban score. All outgoing traffic goes through one bounded queue, so a slow peer
can never block the node.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Awaitable, Callable, Dict, Optional, Tuple

from blockforge.network.messages import (
    HEADER_LEN,
    PROTOCOL_VERSION,
    MessageError,
    Message,
    Ping,
    Pong,
    Verack,
    Version,
    decode_payload,
    encode_message,
    parse_header,
)

log = logging.getLogger("blockforge.peer")

HANDSHAKE_TIMEOUT = 10.0
IDLE_TIMEOUT = 120.0          # no message at all for this long -> disconnect
PING_INTERVAL = 30.0
PONG_TIMEOUT = 20.0
WRITE_TIMEOUT = 30.0
SEND_QUEUE_MAX = 256
MAX_TIME_OFFSET = 2 * 60 * 60  # seconds of clock difference tolerated at handshake
BAN_THRESHOLD = 100

MSG_RATE, MSG_BURST = 50.0, 200.0                    # messages per second
BYTE_RATE, BYTE_BURST = 512_000.0, 4_000_000.0       # bytes per second (burst >= MAX_PAYLOAD)

Handler = Callable[["Peer", Message], Awaitable[None]]


class PeerError(Exception):
    """Base class for connection-level failures."""


class HandshakeError(PeerError):
    pass


class PeerClosed(PeerError):
    pass


class _TokenBucket:
    def __init__(self, rate: float, burst: float) -> None:
        self._rate, self._burst = rate, burst
        self._tokens = burst
        self._last = time.monotonic()

    def take(self, amount: float) -> bool:
        now = time.monotonic()
        self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens < amount:
            return False
        self._tokens -= amount
        return True


class Peer:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        magic: bytes,
        chain_id: int,
        outbound: bool,
        address: Tuple[str, int],
        local_nonce: int,
        on_close: Optional[Callable[["Peer"], None]] = None,
    ) -> None:
        self._reader, self._writer = reader, writer
        self._magic, self._chain_id = magic, chain_id
        self.outbound = outbound
        self.address = address                  # remote (host, port) of this socket
        self._local_nonce = local_nonce
        self._on_close = on_close

        self.remote: Optional[Version] = None   # set after handshake
        self.ready = False
        self.banned = False
        self.ban_score = 0
        self.close_reason = ""
        self.connected_at = time.time()
        self.last_recv = time.monotonic()
        self.bytes_in = 0
        self.bytes_out = 0
        self.latency: Optional[float] = None

        self._queue: "asyncio.Queue[bytes]" = asyncio.Queue(maxsize=SEND_QUEUE_MAX)
        self._closed = False
        self._tasks: list = []
        self._pending_ping: Optional[Tuple[int, float]] = None
        self._msg_bucket = _TokenBucket(MSG_RATE, MSG_BURST)
        self._byte_bucket = _TokenBucket(BYTE_RATE, BYTE_BURST)
        self.known_inv: set = set()             # hashes this peer has announced or been sent

    # ---------------------------------------------------------------- identity
    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def advertised_address(self) -> Optional[Tuple[str, int]]:
        """Address other nodes can dial to reach this peer, if it accepts inbound."""
        if self.remote is None or self.remote.listen_port == 0:
            return None
        return (self.address[0], self.remote.listen_port)

    def info(self) -> Dict[str, object]:
        return {
            "address": f"{self.address[0]}:{self.address[1]}",
            "direction": "outbound" if self.outbound else "inbound",
            "height": self.remote.height if self.remote else None,
            "user_agent": self.remote.user_agent.decode("ascii", "replace") if self.remote else None,
            "latency_ms": None if self.latency is None else round(self.latency * 1000, 1),
            "ban_score": self.ban_score,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "connected_at": int(self.connected_at),
        }

    # --------------------------------------------------------------- handshake
    async def handshake(self, ours: Version) -> Version:
        """Exchange version/verack. Raises HandshakeError on any problem."""
        try:
            theirs = await asyncio.wait_for(self._handshake(ours), HANDSHAKE_TIMEOUT)
        except asyncio.TimeoutError as exc:
            self.close("handshake timeout")
            raise HandshakeError("handshake timeout") from exc
        except (PeerError, MessageError, OSError) as exc:
            self.close(f"handshake failed: {exc}")
            raise HandshakeError(str(exc)) from exc
        self.remote = theirs
        self.ready = True
        return theirs

    async def _handshake(self, ours: Version) -> Version:
        if self.outbound:
            await self._write_now(ours)
            theirs = await self._expect(Version)
        else:
            theirs = await self._expect(Version)
            await self._write_now(ours)
        self._check_version(theirs)
        await self._write_now(Verack())
        await self._expect(Verack)
        return theirs

    def _check_version(self, v: Version) -> None:
        if v.protocol_version < PROTOCOL_VERSION:
            raise HandshakeError("protocol version too old")
        if v.chain_id != self._chain_id:
            raise HandshakeError("different network")
        if v.nonce == self._local_nonce:
            raise HandshakeError("connected to self")
        if abs(v.timestamp - int(time.time())) > MAX_TIME_OFFSET:
            raise HandshakeError("clock offset too large")

    async def _expect(self, cls: type) -> Message:
        msg = await self._read_message()
        if not isinstance(msg, cls):
            raise HandshakeError(f"expected {cls.command}, got {msg.command}")
        return msg

    # ---------------------------------------------------------------- raw I/O
    async def _write_now(self, msg: Message) -> None:
        frame = encode_message(self._magic, msg)
        self._writer.write(frame)
        await asyncio.wait_for(self._writer.drain(), WRITE_TIMEOUT)
        self.bytes_out += len(frame)

    async def _read_message(self) -> Message:
        try:
            header = await self._reader.readexactly(HEADER_LEN)
            command, length, checksum = parse_header(self._magic, header)
            payload = await self._reader.readexactly(length) if length else b""
        except (asyncio.IncompleteReadError, ConnectionError) as exc:
            raise PeerClosed("connection closed") from exc
        self.last_recv = time.monotonic()
        self.bytes_in += HEADER_LEN + length
        return decode_payload(command, checksum, payload)

    # ----------------------------------------------------------------- sending
    def send(self, msg: Message) -> bool:
        """Queue a message. Returns False if the peer is closed or was dropped for lagging."""
        if self._closed:
            return False
        try:
            frame = encode_message(self._magic, msg)
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            self.close("send queue overflow")
            return False
        return True

    async def _writer_loop(self) -> None:
        try:
            while True:
                frame = await self._queue.get()
                self._writer.write(frame)
                await asyncio.wait_for(self._writer.drain(), WRITE_TIMEOUT)
                self.bytes_out += len(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.close(f"write failed: {exc}")

    # --------------------------------------------------------------- keepalive
    async def _keepalive_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(PING_INTERVAL)
                if self._pending_ping is not None:
                    if time.monotonic() - self._pending_ping[1] > PONG_TIMEOUT:
                        self.close("pong timeout")
                        return
                    continue
                nonce = secrets.randbits(64)
                self._pending_ping = (nonce, time.monotonic())
                self.send(Ping(nonce))
        except asyncio.CancelledError:
            raise

    # --------------------------------------------------------------- main loop
    async def run(self, handler: Handler) -> None:
        """Read and dispatch messages until the connection ends."""
        if not self.ready:
            raise PeerError("handshake not completed")
        self._tasks = [asyncio.create_task(self._writer_loop()),
                       asyncio.create_task(self._keepalive_loop())]
        try:
            while not self._closed:
                msg = await asyncio.wait_for(self._read_message(), IDLE_TIMEOUT)
                if not self._msg_bucket.take(1):
                    self.misbehave(10, "message rate exceeded")
                    continue
                if not self._byte_bucket.take(HEADER_LEN + len(msg.encode_payload())):
                    self.misbehave(10, "bandwidth exceeded")
                    continue
                await self._dispatch(msg, handler)
        except asyncio.TimeoutError:
            self.close("idle timeout")
        except MessageError as exc:
            self.misbehave(BAN_THRESHOLD, f"malformed frame: {exc}")
        except PeerError as exc:
            self.close(str(exc))
        except asyncio.CancelledError:
            self.close("cancelled")
            raise
        finally:
            self.close(self.close_reason or "ended")

    async def _dispatch(self, msg: Message, handler: Handler) -> None:
        if isinstance(msg, Ping):
            self.send(Pong(msg.nonce))
        elif isinstance(msg, Pong):
            if self._pending_ping and msg.nonce == self._pending_ping[0]:
                self.latency = time.monotonic() - self._pending_ping[1]
                self._pending_ping = None
            else:
                self.misbehave(10, "unsolicited pong")
        elif isinstance(msg, (Version, Verack)):
            self.misbehave(10, "duplicate handshake message")
        else:
            try:
                await handler(self, msg)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("handler failed for %s from %s", msg.command, self.address)

    # ----------------------------------------------------------------- control
    def misbehave(self, points: int, reason: str) -> None:
        """Add to the ban score; disconnect and flag as banned at the threshold."""
        self.ban_score += points
        log.warning("peer %s:%d misbehaved (+%d, total %d): %s",
                    self.address[0], self.address[1], points, self.ban_score, reason)
        if self.ban_score >= BAN_THRESHOLD:
            self.banned = True
            self.close(f"banned: {reason}")

    def close(self, reason: str = "") -> None:
        """Idempotent; safe to call from anywhere, including handlers."""
        if self._closed:
            return
        self._closed = True
        self.ready = False
        self.close_reason = reason
        me = asyncio.current_task()
        for task in self._tasks:
            if task is not me:
                task.cancel()
        try:
            self._writer.close()
        except Exception:
            pass
        log.info("peer %s:%d closed: %s", self.address[0], self.address[1], reason)
        if self._on_close is not None:
            try:
                self._on_close(self)
            except Exception:
                log.exception("on_close callback failed")

    async def wait_closed(self) -> None:
        try:
            await self._writer.wait_closed()
        except Exception:
            pass