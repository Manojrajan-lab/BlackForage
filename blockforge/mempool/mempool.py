"""Pending-transaction pool for BlockForge (account model).

Per sender, pending transactions form a gapless nonce chain starting at the
sender's confirmed account nonce. Admission checks:
  * stateless validity (signature, fee floor, size, chain_id)
  * nonce is either the next expected one or replaces an existing one
    (replace-by-fee needs a fee at least 10% higher)
  * sender balance covers every pending amount + fee, including this one
  * pool-wide and per-sender limits; when full, a new tx must out-pay the
    lowest fee-rate tail transaction, which is then evicted

Fee rate is integer fee-per-1000-bytes, so ordering is deterministic.
"""
from __future__ import annotations

import heapq
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from blockforge.consensus.params import ConsensusParams
from blockforge.core.block import Block
from blockforge.core.transaction import Transaction, TransactionError
from blockforge.storage.chainstate import ChainState

RBF_BUMP_NUM, RBF_BUMP_DEN = 11, 10  # replacement fee >= old fee * 1.1


class MempoolError(ValueError):
    """Raised when a transaction is rejected by the mempool."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


@dataclass(frozen=True)
class Entry:
    tx: Transaction
    sender: bytes
    size: int
    fee_rate: int  # base units per 1000 bytes
    added_at: float
    seq: int


class Mempool:
    def __init__(
        self,
        chainstate: ChainState,
        params: ConsensusParams,
        max_txs: int = 5_000,
        max_bytes: int = 10_000_000,
        max_per_sender: int = 25,
        ttl_seconds: int = 24 * 3600,
    ) -> None:
        self._state = chainstate
        self._params = params
        self._max_txs = max_txs
        self._max_bytes = max_bytes
        self._max_per_sender = max_per_sender
        self._ttl = ttl_seconds
        self._lock = threading.RLock()
        self._by_txid: Dict[bytes, Entry] = {}
        self._by_sender: Dict[bytes, Dict[int, Entry]] = {}
        self._bytes = 0
        self._seq = 0

    # ------------------------------------------------------------------ reads
    def __len__(self) -> int:
        with self._lock:
            return len(self._by_txid)

    def __contains__(self, txid: bytes) -> bool:
        with self._lock:
            return txid in self._by_txid

    def get(self, txid: bytes) -> Optional[Transaction]:
        with self._lock:
            e = self._by_txid.get(txid)
            return e.tx if e else None

    def total_bytes(self) -> int:
        with self._lock:
            return self._bytes

    def pending_for(self, sender: bytes) -> List[Transaction]:
        with self._lock:
            chain = self._by_sender.get(sender, {})
            return [chain[n].tx for n in sorted(chain)]

    def next_nonce(self, sender: bytes) -> int:
        """Nonce a wallet should use for its next transaction."""
        with self._lock:
            _, nonce = self._state.get_account(sender)
            chain = self._by_sender.get(sender, {})
            while nonce in chain:
                nonce += 1
            return nonce

    def pending_spend(self, sender: bytes) -> int:
        with self._lock:
            return sum(e.tx.amount + e.tx.fee for e in self._by_sender.get(sender, {}).values())

    # ------------------------------------------------------------------ admit
    def add(self, tx: Transaction, now: Optional[float] = None) -> bytes:
        """Validate and insert a transaction. Returns its txid or raises MempoolError."""
        now = time.time() if now is None else now
        if tx.is_coinbase:
            raise MempoolError("coinbase")
        try:
            tx.validate_stateless(self._params)
        except TransactionError as exc:
            raise MempoolError("invalid", str(exc)) from exc

        sender = tx.sender_key_hash
        txid = tx.txid
        with self._lock:
            if txid in self._by_txid:
                raise MempoolError("duplicate")

            balance, confirmed_nonce = self._state.get_account(sender)
            chain = self._by_sender.get(sender, {})
            next_nonce = confirmed_nonce
            while next_nonce in chain:
                next_nonce += 1

            if tx.nonce < confirmed_nonce:
                raise MempoolError("stale-nonce", f"account nonce is {confirmed_nonce}")
            if tx.nonce > next_nonce:
                raise MempoolError("nonce-gap", f"expected {next_nonce}")

            replaced = chain.get(tx.nonce)
            if replaced is not None:
                if tx.fee * RBF_BUMP_DEN < replaced.tx.fee * RBF_BUMP_NUM or tx.fee <= replaced.tx.fee:
                    raise MempoolError("fee-too-low-to-replace")
            elif len(chain) >= self._max_per_sender:
                raise MempoolError("sender-limit")

            spend = tx.amount + tx.fee + sum(
                e.tx.amount + e.tx.fee for n, e in chain.items() if n != tx.nonce
            )
            if balance < spend:
                raise MempoolError("insufficient-funds")

            entry = Entry(tx, sender, tx.size, tx.fee * 1000 // max(tx.size, 1), now, self._seq)
            self._seq += 1

            if replaced is not None:
                self._drop(replaced)
            elif not self._make_room(entry):
                raise MempoolError("pool-full")
            self._insert(entry)
            return txid

    # ----------------------------------------------------------------- select
    def select_for_block(self, max_bytes: int, max_txs: int) -> Tuple[List[Transaction], int]:
        """Pick transactions for a block: best fee rate first, nonce order per sender.

        Returns (transactions, total_fees). Callers reserve room for the coinbase.
        """
        with self._lock:
            heads: Dict[bytes, int] = {}
            heap: List[Tuple[int, int, bytes]] = []
            for sender, chain in self._by_sender.items():
                _, nonce = self._state.get_account(sender)
                if nonce in chain:
                    heads[sender] = nonce
                    e = chain[nonce]
                    heapq.heappush(heap, (-e.fee_rate, e.seq, sender))

            picked: List[Transaction] = []
            used, fees = 0, 0
            while heap and len(picked) < max_txs:
                _, _, sender = heapq.heappop(heap)
                nonce = heads[sender]
                e = self._by_sender[sender][nonce]
                if used + e.size > max_bytes:
                    continue  # this sender's chain stops here; later nonces can't be included
                picked.append(e.tx)
                used += e.size
                fees += e.tx.fee
                nxt = self._by_sender[sender].get(nonce + 1)
                if nxt is not None:
                    heads[sender] = nonce + 1
                    heapq.heappush(heap, (-nxt.fee_rate, nxt.seq, sender))
            return picked, fees

    # ------------------------------------------------------------ chain events
    def remove_for_block(self, block: Block) -> None:
        """Drop confirmed transactions and anything they made stale or unaffordable."""
        with self._lock:
            touched = set()
            for tx in block.transactions:
                if tx.is_coinbase:
                    continue
                sender = tx.sender_key_hash
                touched.add(sender)
                chain = self._by_sender.get(sender)
                if chain:
                    for nonce in [n for n in chain if n <= tx.nonce]:
                        self._drop(chain[nonce])
            for sender in touched:
                self._revalidate(sender)

    def readd_after_reorg(self, blocks: Iterable[Block]) -> int:
        """Re-admit transactions from reverted blocks (oldest first). Returns count re-added."""
        added = 0
        for block in blocks:
            for tx in block.transactions:
                if tx.is_coinbase:
                    continue
                try:
                    self.add(tx)
                    added += 1
                except MempoolError:
                    pass
        with self._lock:
            for sender in list(self._by_sender):
                self._revalidate(sender)
        return added

    def expire(self, now: Optional[float] = None) -> int:
        """Remove transactions older than the TTL (and their dependents)."""
        now = time.time() if now is None else now
        removed = 0
        with self._lock:
            for e in [e for e in self._by_txid.values() if now - e.added_at > self._ttl]:
                if e.tx.txid in self._by_txid:
                    removed += self._drop_with_dependents(e)
        return removed

    def clear(self) -> None:
        with self._lock:
            self._by_txid.clear()
            self._by_sender.clear()
            self._bytes = 0

    # ---------------------------------------------------------------- internals
    def _insert(self, e: Entry) -> None:
        self._by_txid[e.tx.txid] = e
        self._by_sender.setdefault(e.sender, {})[e.tx.nonce] = e
        self._bytes += e.size

    def _drop(self, e: Entry) -> None:
        if self._by_txid.pop(e.tx.txid, None) is None:
            return
        chain = self._by_sender.get(e.sender)
        if chain is not None:
            chain.pop(e.tx.nonce, None)
            if not chain:
                del self._by_sender[e.sender]
        self._bytes -= e.size

    def _drop_with_dependents(self, e: Entry) -> int:
        chain = self._by_sender.get(e.sender, {})
        doomed = [chain[n] for n in sorted(chain) if n >= e.tx.nonce]
        for d in doomed:
            self._drop(d)
        return len(doomed)

    def _revalidate(self, sender: bytes) -> None:
        """Keep the longest valid prefix of a sender's chain after state changed."""
        chain = self._by_sender.get(sender)
        if not chain:
            return
        balance, nonce = self._state.get_account(sender)
        for n in [n for n in chain if n < nonce]:
            self._drop(chain[n])
        spend = 0
        while nonce in self._by_sender.get(sender, {}):
            e = self._by_sender[sender][nonce]
            spend += e.tx.amount + e.tx.fee
            if spend > balance:
                self._drop_with_dependents(e)
                return
            nonce += 1
        # entries beyond a gap can never be mined; discard them
        for e in list(self._by_sender.get(sender, {}).values()):
            if e.tx.nonce >= nonce:
                self._drop(e)

    def _make_room(self, new: Entry) -> bool:
        """Evict lowest fee-rate tail transactions until `new` fits; False if it can't."""
        while (len(self._by_txid) + 1 > self._max_txs
               or self._bytes + new.size > self._max_bytes):
            tails = [chain[max(chain)] for chain in self._by_sender.values()]
            if not tails:
                return False
            worst = min(tails, key=lambda e: (e.fee_rate, -e.seq))
            if new.fee_rate <= worst.fee_rate:
                return False
            self._drop(worst)
        return True