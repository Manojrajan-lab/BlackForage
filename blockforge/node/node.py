"""BlockForge node: wires storage, validation, mempool and the miner together.

Network-agnostic. The P2P layer and the API both talk to this class:
  * submit_block / submit_transaction   (input from peers or API)
  * subscribe(callback)                 (events for broadcasting)
  * start_mining / stop_mining          (real proof-of-work, no simulation)
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from blockforge.consensus.params import ConsensusParams
from blockforge.consensus.pow import MAX_NONCE, mine
from blockforge.consensus.rewards import block_subsidy
from blockforge.consensus.validation import BLOCK_VERSION, ValidationError
from blockforge.core.block import HEADER_SIZE, Block
from blockforge.core.transaction import MAX_MEMO_LEN, Transaction
from blockforge.mempool.mempool import Mempool, MempoolError
from blockforge.node.fork_choice import ForkChoice, ForkChoiceError, Outcome, Status
from blockforge.storage.chainstate import ChainState, ChainStateError
from blockforge.storage.database import Database

log = logging.getLogger("blockforge.node")

NONCE_CHUNK = 1 << 18          # nonces tried before checking for a stale template
TEMPLATE_MAX_AGE = 30.0        # seconds before the miner rebuilds its template
COINBASE_EXTRA = b"BlockForge"

Listener = Callable[[str, Any], None]  # event in {"block", "tx"}; payload Outcome | Transaction


class Node:
    def __init__(self, params: ConsensusParams, db_path: str = "blockforge.db") -> None:
        self.params = params
        self.db = Database(db_path)
        self.state = ChainState(self.db, params)
        self.fork_choice = ForkChoice(self.state, params)
        self.mempool = Mempool(self.state, params)
        self._chain_lock = threading.RLock()
        self._listeners: List[Listener] = []
        self._miner: Optional[threading.Thread] = None
        self._miner_stop = threading.Event()
        self._started = False

    # -------------------------------------------------------------- lifecycle
    def start(self) -> None:
        with self._chain_lock:
            if self._started:
                return
            self.fork_choice.initialize()
            self._started = True
        tip = self.state.tip()
        log.info("node started network=%s height=%d tip=%s",
                 self.params.network.value, tip[0], tip[1].hex())

    def stop(self) -> None:
        self.stop_mining()
        with self._chain_lock:
            self.db.close()
            self._started = False

    def subscribe(self, callback: Listener) -> None:
        self._listeners.append(callback)

    def _notify(self, event: str, payload: Any) -> None:
        for cb in list(self._listeners):
            try:
                cb(event, payload)
            except Exception:  # a broken listener must never break consensus
                log.exception("listener failed for event %s", event)

    # ------------------------------------------------------------------ input
    def submit_block(self, block: Block) -> List[Outcome]:
        """Validate and process a block. Raises ValidationError/ChainStateError/ForkChoiceError."""
        with self._chain_lock:
            outcomes = self.fork_choice.process_block(block)
            for out in outcomes:
                if out.status in (Status.EXTENDED, Status.REORG):
                    self.mempool.readd_after_reorg(out.reverted)
                    for applied in out.applied:
                        self.mempool.remove_for_block(applied)
        for out in outcomes:
            if out.status in (Status.EXTENDED, Status.REORG):
                self._notify("block", out)
        return outcomes

    def submit_transaction(self, tx: Transaction) -> bytes:
        """Admit a transaction to the mempool. Raises MempoolError."""
        txid = self.mempool.add(tx)
        self._notify("tx", tx)
        return txid

    # ------------------------------------------------------------------ reads
    def tip(self) -> Tuple[int, bytes, int]:
        return self.state.tip()

    def get_account(self, key_hash: bytes) -> Dict[str, int]:
        balance, nonce = self.state.get_account(key_hash)
        return {
            "balance": balance,
            "nonce": nonce,
            "spendable": max(0, balance - self.mempool.pending_spend(key_hash)),
            "next_nonce": self.mempool.next_nonce(key_hash),
        }

    def get_block_by_hash(self, block_hash: bytes) -> Optional[Block]:
        return self.state.get_block(block_hash)

    def get_block_by_height(self, height: int) -> Optional[Block]:
        return self.state.get_block_at(height)

    def get_transaction(self, txid: bytes) -> Optional[Dict[str, Any]]:
        pending = self.mempool.get(txid)
        if pending is not None:
            return {"tx": pending, "height": None, "position": None, "confirmed": False}
        loc = self.db.get_tx_location(txid)
        if loc is None:
            return None
        block = self.state.get_block_at(loc[0])
        if block is None or loc[1] >= len(block.transactions):
            return None
        return {"tx": block.transactions[loc[1]], "height": loc[0],
                "position": loc[1], "confirmed": True}

    def status(self) -> Dict[str, Any]:
        height, tip_hash, chainwork = self.state.tip()
        return {
            "network": self.params.network.value,
            "chain_id": self.params.chain_id,
            "height": height,
            "tip": tip_hash.hex(),
            "chainwork": chainwork,
            "mempool_txs": len(self.mempool),
            "mempool_bytes": self.mempool.total_bytes(),
            "total_supply": self.db.get_total_supply(),
            "mining": self.is_mining(),
        }

    # --------------------------------------------------------------- template
    def build_template(self, miner_key_hash: bytes, now: Optional[int] = None) -> Block:
        """Assemble an unmined block on the current tip paying `miner_key_hash`."""
        p = self.params
        with self._chain_lock:
            tip_height, tip_hash, _ = self.state.tip()
            height = tip_height + 1
            bits = self.fork_choice.required_bits_for_child(tip_hash)
            timestamp = max(int(time.time()) if now is None else now,
                            self.fork_choice.mtp_of(tip_hash) + 1)

            # Coinbase size does not depend on its amount (fixed-width u64).
            probe = Transaction.create_coinbase(p, height, miner_key_hash, 0,
                                                COINBASE_EXTRA[:MAX_MEMO_LEN])
            budget = (p.max_block_bytes - HEADER_SIZE - 4 - (4 + probe.size)
                      - 4 * p.max_block_txs)
            txs, fees = self.mempool.select_for_block(max(budget, 0), p.max_block_txs - 1)

            coinbase = Transaction.create_coinbase(
                p, height, miner_key_hash, block_subsidy(p, height) + fees,
                COINBASE_EXTRA[:MAX_MEMO_LEN],
            )
            return Block.build(BLOCK_VERSION, tip_hash, timestamp, bits, height,
                               [coinbase, *txs])

    # ----------------------------------------------------------------- mining
    def is_mining(self) -> bool:
        return self._miner is not None and self._miner.is_alive()

    def start_mining(self, miner_key_hash: bytes) -> None:
        if len(miner_key_hash) != 20:
            raise ValueError("miner_key_hash must be 20 bytes")
        if self.is_mining():
            return
        self._miner_stop = threading.Event()
        self._miner = threading.Thread(
            target=self._mine_loop, args=(miner_key_hash, self._miner_stop),
            name="blockforge-miner", daemon=True,
        )
        self._miner.start()

    def stop_mining(self) -> None:
        self._miner_stop.set()
        if self._miner is not None:
            self._miner.join(timeout=10)
            self._miner = None

    def _mine_loop(self, key_hash: bytes, stop: threading.Event) -> None:
        log.info("miner started")
        while not stop.is_set():
            try:
                block = self.build_template(key_hash)
            except Exception:
                log.exception("template build failed")
                stop.wait(1.0)
                continue

            prefix, bits, parent = block.header.prefix(), block.header.bits, block.prev_hash
            built_at = time.monotonic()
            nonce = 0
            while not stop.is_set() and nonce <= MAX_NONCE:
                found = mine(prefix, bits, start_nonce=nonce,
                             max_nonce=min(nonce + NONCE_CHUNK - 1, MAX_NONCE), stop_event=stop)
                if found is not None:
                    self._submit_mined(block.with_nonce(found[0]))
                    break
                nonce += NONCE_CHUNK
                if self.state.tip()[1] != parent or time.monotonic() - built_at > TEMPLATE_MAX_AGE:
                    break  # new tip or stale template: rebuild
        log.info("miner stopped")

    def _submit_mined(self, block: Block) -> None:
        try:
            self.submit_block(block)
            log.info("mined block height=%d hash=%s", block.height, block.hash_hex)
        except (ValidationError, ChainStateError, ForkChoiceError) as exc:
            log.warning("own block rejected: %s", exc)