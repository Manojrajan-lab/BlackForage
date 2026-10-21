"""P2P manager: listener, outbound dialer, address book, block/tx relay and chain sync.

All consensus work (block/tx validation, database access) runs in worker
threads via asyncio.to_thread, so the event loop never blocks on the node's locks.

Constructor options:
    port           TCP port to listen on (0 = pick a free port, None = do not listen)
    seeds          [(host, port), ...] always kept in the address book
    allow_private  accept loopback/private addresses from gossip (for dev and test networks)
    peers_file     optional JSON file used to persist the address book
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from blockforge.consensus.validation import ValidationError
from blockforge.mempool.mempool import MempoolError
from blockforge.network.messages import (
    INV_BLOCK,
    INV_TX,
    MAX_ADDRS,
    MAX_INV_ITEMS,
    PROTOCOL_VERSION,
    Addr,
    BlockMsg,
    GetAddr,
    GetBlocks,
    GetData,
    Inv,
    Message,
    MessageError,
    NotFound,
    Reject,
    TxMsg,
    Version,
    network_magic,
)
from blockforge.network.peer import HandshakeError, Peer
from blockforge.node.fork_choice import ForkChoiceError, Status
from blockforge.node.node import Node
from blockforge.storage.chainstate import ChainStateError

log = logging.getLogger("blockforge.p2p")

USER_AGENT = b"BlockForge/0.1"
CONNECT_INTERVAL = 5.0
DIAL_TIMEOUT = 5.0
MAINTENANCE_INTERVAL = 30.0
INFLIGHT_TTL = 60.0
BAN_SECONDS = 24 * 3600
MAX_PER_IP = 3
MAX_ADDR_BOOK = 1000
MAX_GETDATA = 64                 # items served or requested per getdata message
MAX_PEER_INFLIGHT = 1000
MAX_TOTAL_INFLIGHT = 5000
KNOWN_INV_LIMIT = 20_000
MIN_GETBLOCKS_GAP = 2.0
MIN_ADDR_GAP = 10.0

_IMMEDIATE_BAN_FORK_CODES = {"known-invalid", "invalid-parent", "unexpected-genesis"}


@dataclass
class _AddrInfo:
    last_seen: int
    failures: int = 0
    next_try: float = 0.0
    trusted: bool = False


@dataclass
class _PeerState:
    last_getblocks_sent: float = 0.0
    last_getblocks_recv: float = 0.0
    last_addr_recv: float = 0.0
    sent_addr: bool = False
    more_expected: bool = False
    inflight: Set[bytes] = field(default_factory=set)


class P2PNetwork:
    def __init__(
        self,
        node: Node,
        host: str = "0.0.0.0",
        port: Optional[int] = 0,
        seeds: Sequence[Tuple[str, int]] = (),
        max_inbound: int = 32,
        max_outbound: int = 8,
        allow_private: bool = False,
        peers_file: Optional[str] = None,
    ) -> None:
        self.node = node
        self._host = host
        self._port = port
        self.listen_port = 0
        self._seeds = [(h, int(p)) for h, p in seeds]
        self.max_inbound = max_inbound
        self.max_outbound = max_outbound
        self.allow_private = allow_private
        self._peers_file = peers_file

        self._magic = network_magic(node.params.chain_id)
        self._nonce = secrets.randbits(64)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[asyncio.base_events.Server] = None
        self._tasks: List[asyncio.Task] = []

        self._conns: Set[Peer] = set()      # every open connection, including mid-handshake
        self._peers: Set[Peer] = set()      # handshake completed
        self._state: Dict[Peer, _PeerState] = {}
        self._dialing: Set[Tuple[str, int]] = set()
        self._book: Dict[Tuple[str, int], _AddrInfo] = {}
        self._bans: Dict[str, float] = {}
        self._inflight: Dict[bytes, Tuple[Peer, float]] = {}

    # --------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        await asyncio.to_thread(self._load_peers)
        for host, port in self._seeds:
            self._add_addr(host, port, trusted=True)
        if self._port is not None:
            self._server = await asyncio.start_server(self._on_inbound, self._host, self._port)
            self.listen_port = self._server.sockets[0].getsockname()[1]
            log.info("listening on %s:%d", self._host, self.listen_port)
        self.node.subscribe(self._on_node_event)
        self._tasks = [
            asyncio.create_task(self._connect_loop()),
            asyncio.create_task(self._maintenance_loop()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        for peer in list(self._conns):
            peer.close("shutdown")
        self._save_peers()

    async def connect_to(self, host: str, port: int) -> None:
        """Dial a specific address now (also remembers it in the address book)."""
        self._add_addr(host, int(port), trusted=True)
        if (host, int(port)) not in self._dialing:
            asyncio.create_task(self._dial((host, int(port))))

    # ------------------------------------------------------------------- stats
    def peer_count(self) -> int:
        return len(self._peers)

    def peers_info(self) -> List[Dict[str, object]]:
        return [p.info() for p in list(self._peers)]

    def stats(self) -> Dict[str, Any]:
        return {
            "peers": len(self._peers),
            "inbound": sum(1 for p in self._peers if not p.outbound),
            "outbound": sum(1 for p in self._peers if p.outbound),
            "known_addresses": len(self._book),
            "banned": len(self._bans),
            "listen_port": self.listen_port,
        }

    # -------------------------------------------------------------- connections
    async def _on_inbound(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peername = writer.get_extra_info("peername")
        if not peername:
            writer.close()
            return
        addr = (peername[0], peername[1])
        inbound = sum(1 for p in self._conns if not p.outbound)
        same_ip = sum(1 for p in self._conns if p.address[0] == addr[0])
        if self._is_banned(addr[0]) or inbound >= self.max_inbound or same_ip >= MAX_PER_IP:
            writer.close()
            return
        await self._run_connection(reader, writer, addr, outbound=False)

    async def _dial(self, addr: Tuple[str, int]) -> None:
        self._dialing.add(addr)
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(*addr), DIAL_TIMEOUT)
        except (OSError, asyncio.TimeoutError):
            self._dialing.discard(addr)
            self._record_failure(addr)
            return
        self._dialing.discard(addr)
        await self._run_connection(reader, writer, addr, outbound=True)

    async def _run_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                              addr: Tuple[str, int], outbound: bool) -> None:
        peer = Peer(reader, writer, self._magic, self.node.params.chain_id, outbound,
                    addr, self._nonce, on_close=self._on_peer_closed)
        self._conns.add(peer)
        self._state[peer] = _PeerState()
        try:
            try:
                theirs = await peer.handshake(self._our_version())
            except HandshakeError:
                if outbound:
                    self._record_failure(addr)
                return

            if any(p.remote is not None and p.remote.nonce == theirs.nonce for p in self._peers):
                peer.close("duplicate connection")
                return
            self._peers.add(peer)

            adv = peer.advertised_address
            if adv is not None and self._valid_gossip(adv[0], adv[1]):
                self._add_addr(adv[0], adv[1])
            if outbound:
                self._record_success(addr)
                if len(self._book) < 50:
                    peer.send(GetAddr())

            if theirs.height > self.node.tip()[0]:
                await self._request_blocks(peer)
            await peer.run(self._handle)
        finally:
            peer.close("connection ended")
            await peer.wait_closed()

    def _on_peer_closed(self, peer: Peer) -> None:
        self._conns.discard(peer)
        self._peers.discard(peer)
        state = self._state.pop(peer, None)
        if state is not None:
            for h in state.inflight:
                entry = self._inflight.get(h)
                if entry is not None and entry[0] is peer:
                    del self._inflight[h]
        if peer.banned:
            self._bans[peer.address[0]] = time.time() + BAN_SECONDS

    def _our_version(self) -> Version:
        height, tip_hash, _ = self.node.tip()
        return Version(PROTOCOL_VERSION, self.node.params.chain_id, int(time.time()),
                       self._nonce, self.listen_port, height, tip_hash, USER_AGENT)

    # --------------------------------------------------------------- dial loop
    async def _connect_loop(self) -> None:
        while True:
            await asyncio.sleep(CONNECT_INTERVAL)
            try:
                outbound = sum(1 for p in self._conns if p.outbound) + len(self._dialing)
                need = self.max_outbound - outbound
                if need > 0:
                    for addr in self._pick_candidates(need):
                        asyncio.create_task(self._dial(addr))
            except Exception:
                log.exception("connect loop error")

    def _pick_candidates(self, count: int) -> List[Tuple[str, int]]:
        connected = set()
        for p in self._conns:
            connected.add(p.address)
            if p.advertised_address:
                connected.add(p.advertised_address)
        now = time.time()
        eligible = [
            addr for addr, info in self._book.items()
            if addr not in connected and addr not in self._dialing
            and info.next_try <= now and not self._is_banned(addr[0])
        ]
        random.shuffle(eligible)
        return eligible[:count]

    # ------------------------------------------------------------- address book
    def _valid_gossip(self, host: str, port: int) -> bool:
        if not 1 <= port <= 65535:
            return False
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        if ip.is_unspecified or ip.is_multicast:
            return False
        return True if self.allow_private else ip.is_global

    def _add_addr(self, host: str, port: int, last_seen: Optional[int] = None,
                  trusted: bool = False) -> None:
        key = (host, port)
        seen = int(time.time()) if last_seen is None else last_seen
        info = self._book.get(key)
        if info is not None:
            info.last_seen = max(info.last_seen, seen)
            info.trusted = info.trusted or trusted
            return
        if len(self._book) >= MAX_ADDR_BOOK:
            evictable = [(i.failures, -i.last_seen, k) for k, i in self._book.items() if not i.trusted]
            if not evictable:
                return
            self._book.pop(max(evictable)[2], None)
        self._book[key] = _AddrInfo(last_seen=seen, trusted=trusted)

    def _record_failure(self, addr: Tuple[str, int]) -> None:
        info = self._book.get(addr)
        if info is None:
            return
        info.failures += 1
        info.next_try = time.time() + min(3600.0, 30.0 * (2 ** min(info.failures, 7)))
        if info.failures > 8 and not info.trusted:
            self._book.pop(addr, None)

    def _record_success(self, addr: Tuple[str, int]) -> None:
        info = self._book.get(addr)
        if info is not None:
            info.failures = 0
            info.next_try = 0.0
            info.last_seen = int(time.time())

    def _load_peers(self) -> None:
        if not self._peers_file or not os.path.exists(self._peers_file):
            return
        try:
            with open(self._peers_file, "r", encoding="utf-8") as fh:
                entries = json.load(fh)
            for host, port, seen in entries:
                if isinstance(host, str) and isinstance(port, int) and isinstance(seen, int) \
                        and self._valid_gossip(host, port):
                    self._add_addr(host, port, last_seen=seen)
        except (OSError, ValueError, TypeError):
            log.warning("could not read peers file %s", self._peers_file)

    def _save_peers(self) -> None:
        if not self._peers_file:
            return
        entries = [[h, p, i.last_seen] for (h, p), i in self._book.items()
                   if i.failures < 3 and self._valid_gossip(h, p)]
        tmp = self._peers_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(entries, fh)
            os.replace(tmp, self._peers_file)
        except OSError:
            log.warning("could not write peers file %s", self._peers_file)

    # --------------------------------------------------------------------- bans
    def _is_banned(self, ip: str) -> bool:
        expiry = self._bans.get(ip)
        if expiry is None:
            return False
        if expiry <= time.time():
            del self._bans[ip]
            return False
        return True

    def ban(self, ip: str, seconds: int = BAN_SECONDS) -> None:
        self._bans[ip] = time.time() + seconds
        for peer in list(self._conns):
            if peer.address[0] == ip:
                peer.close("banned by operator")

    def unban(self, ip: str) -> None:
        self._bans.pop(ip, None)

    # -------------------------------------------------------------- maintenance
    async def _maintenance_loop(self) -> None:
        while True:
            await asyncio.sleep(MAINTENANCE_INTERVAL)
            try:
                now = time.monotonic()
                for h, (peer, started) in list(self._inflight.items()):
                    if now - started > INFLIGHT_TTL:
                        del self._inflight[h]
                        st = self._state.get(peer)
                        if st is not None:
                            st.inflight.discard(h)
                for ip in list(self._bans):
                    self._is_banned(ip)
                await asyncio.to_thread(self.node.mempool.expire)
                await asyncio.to_thread(self._save_peers)
            except Exception:
                log.exception("maintenance error")

    # -------------------------------------------------------------------- relay
    def _on_node_event(self, event: str, payload: Any) -> None:
        """Called from any thread by the node; hops onto the event loop."""
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._relay, event, payload)

    def _relay(self, event: str, payload: Any) -> None:
        if event == "block":
            items = tuple((INV_BLOCK, b.hash) for b in payload.applied[-MAX_INV_ITEMS:])
        elif event == "tx":
            items = ((INV_TX, payload.txid),)
        else:
            return
        for peer in list(self._peers):
            if not peer.ready:
                continue
            fresh = tuple(i for i in items if i[1] not in peer.known_inv)
            if fresh:
                for _, h in fresh:
                    self._mark_known(peer, h)
                peer.send(Inv(fresh))

    @staticmethod
    def _mark_known(peer: Peer, h: bytes) -> None:
        if len(peer.known_inv) >= KNOWN_INV_LIMIT:
            peer.known_inv.clear()
        peer.known_inv.add(h)

    # ------------------------------------------------------------ message routing
    async def _handle(self, peer: Peer, msg: Message) -> None:
        if isinstance(msg, Inv) and not isinstance(msg, (GetData, NotFound)):
            await self._on_inv(peer, msg)
        elif isinstance(msg, GetData):
            await self._on_getdata(peer, msg)
        elif isinstance(msg, NotFound):
            self._on_notfound(peer, msg)
        elif isinstance(msg, GetBlocks):
            await self._on_getblocks(peer, msg)
        elif isinstance(msg, BlockMsg):
            await self._on_block(peer, msg)
        elif isinstance(msg, TxMsg):
            await self._on_tx(peer, msg)
        elif isinstance(msg, GetAddr):
            self._on_getaddr(peer)
        elif isinstance(msg, Addr):
            self._on_addr(peer, msg)
        elif isinstance(msg, Reject):
            log.info("peer %s:%d rejected %r: %r", peer.address[0], peer.address[1],
                     msg.rejected_command, msg.reason)

    # ---------------------------------------------------------------------- sync
    async def _request_blocks(self, peer: Peer) -> None:
        st = self._state.get(peer)
        now = time.monotonic()
        if st is None or now - st.last_getblocks_sent < MIN_GETBLOCKS_GAP:
            return
        st.last_getblocks_sent = now
        locator = await asyncio.to_thread(self.node.fork_choice.block_locator)
        if locator:
            peer.send(GetBlocks(tuple(locator)))

    async def _on_getblocks(self, peer: Peer, msg: GetBlocks) -> None:
        st = self._state[peer]
        now = time.monotonic()
        if now - st.last_getblocks_recv < 1.0:
            peer.misbehave(5, "getblocks flood")
            return
        st.last_getblocks_recv = now

        def collect() -> Optional[List[Tuple[int, bytes]]]:
            common = self.node.fork_choice.find_common_height(list(msg.locator))
            if common is None:
                return None
            out: List[Tuple[int, bytes]] = []
            height = common + 1
            while len(out) < MAX_INV_ITEMS:
                block_hash = self.node.db.get_active_hash(height)
                if block_hash is None:
                    break
                out.append((INV_BLOCK, block_hash))
                if block_hash == msg.stop_hash:
                    break
                height += 1
            return out

        items = await asyncio.to_thread(collect)
        if items is None:
            peer.misbehave(10, "no common ancestor in locator")
        elif items:
            peer.send(Inv(tuple(items)))

    async def _on_inv(self, peer: Peer, msg: Inv) -> None:
        st = self._state[peer]
        for _, h in msg.items:
            self._mark_known(peer, h)
        if len(st.inflight) > MAX_PEER_INFLIGHT or len(self._inflight) > MAX_TOTAL_INFLIGHT:
            return
        pending = set(self._inflight)

        def filter_items() -> List[Tuple[int, bytes]]:
            fc = self.node.fork_choice
            want: List[Tuple[int, bytes]] = []
            for kind, h in msg.items:
                if h in pending:
                    continue
                if kind == INV_BLOCK:
                    if not fc.is_known(h) and not fc.is_invalid(h):
                        want.append((kind, h))
                elif h not in self.node.mempool and self.node.db.get_tx_location(h) is None:
                    want.append((kind, h))
            return want

        want = await asyncio.to_thread(filter_items)
        if peer.closed or not want:
            return
        now = time.monotonic()
        wanted: List[Tuple[int, bytes]] = []
        for kind, h in want:
            if h in self._inflight:
                continue
            self._inflight[h] = (peer, now)
            st.inflight.add(h)
            wanted.append((kind, h))
        for i in range(0, len(wanted), MAX_GETDATA):
            peer.send(GetData(tuple(wanted[i:i + MAX_GETDATA])))
        has_blocks = any(kind == INV_BLOCK for kind, _ in wanted)
        st.more_expected = has_blocks and len(msg.items) >= MAX_INV_ITEMS

    async def _on_getdata(self, peer: Peer, msg: GetData) -> None:
        items = msg.items
        if len(items) > MAX_GETDATA:
            peer.misbehave(20, "oversized getdata")
            items = items[:MAX_GETDATA]

        def collect() -> Tuple[List[Message], List[Tuple[int, bytes]]]:
            frames: List[Message] = []
            missing: List[Tuple[int, bytes]] = []
            for kind, h in items:
                if kind == INV_BLOCK:
                    row = self.node.db.get_block_by_hash(h)
                    if row is None:
                        missing.append((kind, h))
                    else:
                        frames.append(BlockMsg(row[3]))
                else:
                    found = self.node.get_transaction(h)
                    if found is None:
                        missing.append((kind, h))
                    else:
                        frames.append(TxMsg.from_tx(found["tx"]))
            return frames, missing

        frames, missing = await asyncio.to_thread(collect)
        for frame in frames:
            if not peer.send(frame):
                return
        if missing:
            peer.send(NotFound(tuple(missing)))

    def _on_notfound(self, peer: Peer, msg: NotFound) -> None:
        st = self._state[peer]
        for _, h in msg.items:
            entry = self._inflight.get(h)
            if entry is not None and entry[0] is peer:
                del self._inflight[h]
            st.inflight.discard(h)

    # ------------------------------------------------------------------- blocks
    async def _on_block(self, peer: Peer, msg: BlockMsg) -> None:
        st = self._state[peer]
        try:
            block = msg.to_block()
        except MessageError as exc:
            peer.misbehave(100, f"malformed block: {exc}")
            return
        h = block.hash
        entry = self._inflight.pop(h, None)
        st.inflight.discard(h)
        if entry is None or entry[0] is not peer:
            peer.misbehave(10, "unsolicited block")
            return
        self._mark_known(peer, h)

        try:
            outcomes = await asyncio.to_thread(self.node.submit_block, block)
        except ValidationError as exc:
            if exc.code == "time-too-new":
                log.info("block from %s:%d too far in the future", *peer.address)
            else:
                peer.misbehave(100, f"invalid block: {exc}")
            return
        except ChainStateError as exc:
            peer.misbehave(100, f"invalid block: {exc}")
            return
        except ForkChoiceError as exc:
            if exc.code in _IMMEDIATE_BAN_FORK_CODES:
                peer.misbehave(100, f"invalid block: {exc}")
            else:
                log.warning("block rejected: %s", exc)
            return
        except Exception:
            log.exception("unexpected error while processing block")
            return

        if outcomes and outcomes[0].status == Status.ORPHAN:
            await self._request_blocks(peer)
        elif st.more_expected and not st.inflight:
            st.more_expected = False
            await self._request_blocks(peer)

    # ------------------------------------------------------------- transactions
    async def _on_tx(self, peer: Peer, msg: TxMsg) -> None:
        st = self._state[peer]
        try:
            tx = msg.to_tx()
        except MessageError as exc:
            peer.misbehave(50, f"malformed transaction: {exc}")
            return
        txid = tx.txid
        entry = self._inflight.pop(txid, None)
        st.inflight.discard(txid)
        if entry is None or entry[0] is not peer:
            peer.misbehave(10, "unsolicited transaction")
            return
        self._mark_known(peer, txid)
        try:
            await asyncio.to_thread(self.node.submit_transaction, tx)
        except MempoolError as exc:
            if exc.code == "invalid":
                peer.misbehave(20, f"invalid transaction: {exc}")
        except Exception:
            log.exception("unexpected error while processing transaction")

    # ---------------------------------------------------------------- addresses
    def _on_getaddr(self, peer: Peer) -> None:
        st = self._state[peer]
        if st.sent_addr:
            return
        st.sent_addr = True
        now = int(time.time())
        good = [
            (h, p, min(i.last_seen, now)) for (h, p), i in self._book.items()
            if i.failures == 0 and self._valid_gossip(h, p) and (h, p) != peer.advertised_address
        ]
        random.shuffle(good)
        if good:
            peer.send(Addr(tuple(good[:MAX_ADDRS])))

    def _on_addr(self, peer: Peer, msg: Addr) -> None:
        st = self._state[peer]
        now = time.monotonic()
        if now - st.last_addr_recv < MIN_ADDR_GAP:
            return
        st.last_addr_recv = now
        wall = int(time.time())
        for host, port, seen in msg.addrs:
            if self._valid_gossip(host, port):
                self._add_addr(host, port, last_seen=min(seen, wall))