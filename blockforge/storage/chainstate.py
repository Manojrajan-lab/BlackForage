"""Account-state transitions for BlockForge.

Applies and reverts blocks against the `accounts` table inside one atomic
database transaction, recording per-block undo data so reorgs are exact.

Rules enforced here (state-dependent only; header/PoW/structure rules live in
consensus/validation.py):
  * every tx passes Transaction.validate_stateless
  * transfer nonce == sender's current account nonce (then nonce += 1)
  * sender balance >= amount + fee
  * coinbase is tx 0 only, nonce == block height, amount <= subsidy + fees
  * no balance may exceed params.max_supply
Any failure rolls the whole block back.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from blockforge.consensus.params import ConsensusParams
from blockforge.consensus.pow import work_from_bits
from blockforge.consensus.rewards import block_subsidy
from blockforge.core.block import ZERO_HASH, Block
from blockforge.core.serialization import Reader, SerializationError, Writer
from blockforge.core.transaction import Transaction, TransactionError
from blockforge.storage.database import Database

KEYHASH_LEN = 20


class ChainStateError(ValueError):
    """Raised when a block cannot be applied or reverted."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


# ------------------------------------------------------------------ undo data
def _encode_undo(original: Dict[bytes, Tuple[int, int]]) -> bytes:
    w = Writer().u32(len(original))
    for key_hash in sorted(original):
        balance, nonce = original[key_hash]
        w.fixed(key_hash, KEYHASH_LEN).u64(balance).u64(nonce)
    return w.getvalue()


def _decode_undo(data: bytes) -> List[Tuple[bytes, int, int]]:
    try:
        r = Reader(data)
        count = r.u32()
        out = [(r.fixed(KEYHASH_LEN), r.u64(), r.u64()) for _ in range(count)]
        r.finish()
    except SerializationError as exc:
        raise ChainStateError("corrupt-undo", str(exc)) from exc
    return out


class _Overlay:
    """In-memory working copy of the accounts a block touches."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self.original: Dict[bytes, Tuple[int, int]] = {}
        self.current: Dict[bytes, Tuple[int, int]] = {}

    def get(self, key_hash: bytes) -> Tuple[int, int]:
        if key_hash not in self.current:
            state = self._db.get_account(key_hash)
            self.original[key_hash] = state
            self.current[key_hash] = state
        return self.current[key_hash]

    def set(self, key_hash: bytes, balance: int, nonce: int) -> None:
        self.get(key_hash)  # make sure the original state is captured
        self.current[key_hash] = (balance, nonce)

    def flush(self) -> None:
        for key_hash, (balance, nonce) in self.current.items():
            self._db.set_account(key_hash, balance, nonce)


class ChainState:
    def __init__(self, db: Database, params: ConsensusParams) -> None:
        self._db = db
        self._params = params

    # ------------------------------------------------------------------ reads
    @property
    def db(self) -> Database:
        return self._db

    def tip(self) -> Optional[Tuple[int, bytes, int]]:
        """(height, hash, chainwork) of the active chain, or None if empty."""
        return self._db.get_tip()

    def get_account(self, key_hash: bytes) -> Tuple[int, int]:
        """(balance, nonce)."""
        return self._db.get_account(key_hash)

    def get_block(self, block_hash: bytes) -> Optional[Block]:
        row = self._db.get_block_by_hash(block_hash)
        return Block.deserialize(row[3], Transaction.deserialize) if row else None

    def get_block_at(self, height: int) -> Optional[Block]:
        block_hash = self._db.get_active_hash(height)
        return self.get_block(block_hash) if block_hash else None

    # ---------------------------------------------------------------- storage
    def store_block(self, block: Block) -> int:
        """Persist a block (any branch) and return its cumulative chainwork.

        The parent must already be stored, except for genesis.
        """
        h = block.header
        own_work = work_from_bits(h.bits)
        if h.height == 0:
            if h.prev_hash != ZERO_HASH:
                raise ChainStateError("bad-prev-hash", "genesis must reference zero hash")
            parent_work = 0
        else:
            parent = self._db.get_block_by_hash(h.prev_hash)
            if parent is None:
                raise ChainStateError("orphan", "parent block unknown")
            if parent[0] != h.height - 1:
                raise ChainStateError("bad-height", "height does not follow parent")
            parent_work = parent[2]
        chainwork = parent_work + own_work
        self._db.put_block(block.hash, h.height, h.prev_hash, chainwork, block.serialize())
        return chainwork

    # ------------------------------------------------------------ transitions
    def apply_block(self, block: Block) -> None:
        """Extend the active chain by `block`, updating accounts atomically."""
        h = block.header
        with self._db.atomic():
            tip = self._db.get_tip()
            if tip is None:
                if h.height != 0 or h.prev_hash != ZERO_HASH:
                    raise ChainStateError("not-genesis", "empty chain requires genesis")
            else:
                if h.height != tip[0] + 1:
                    raise ChainStateError("bad-height", str(h.height))
                if h.prev_hash != tip[1]:
                    raise ChainStateError("not-extending-tip")

            txs = block.transactions
            self._check_shape(block)

            overlay = _Overlay(self._db)
            total_fees = 0
            for tx in txs[1:]:
                total_fees += self._apply_transfer(tx, overlay)

            coinbase = txs[0]
            self._check_stateless(coinbase)
            if coinbase.nonce != h.height:
                raise ChainStateError("bad-coinbase-height")
            if coinbase.amount > block_subsidy(self._params, h.height) + total_fees:
                raise ChainStateError("bad-coinbase-value")
            self._credit(overlay, coinbase.recipient, coinbase.amount)

            self.store_block(block)
            overlay.flush()
            self._db.put_undo(h.height, _encode_undo(overlay.original))
            self._db.set_active(h.height, block.hash)
            for position, tx in enumerate(txs):
                self._db.index_tx(tx.txid, h.height, position, tx.sender_key_hash, tx.recipient)

    def revert_tip(self) -> bytes:
        """Undo the active tip block. Returns the removed block's hash."""
        with self._db.atomic():
            tip = self._db.get_tip()
            if tip is None:
                raise ChainStateError("empty-chain")
            height, block_hash, _ = tip
            if height == 0:
                raise ChainStateError("cannot-revert-genesis")
            data = self._db.get_undo(height)
            if data is None:
                raise ChainStateError("missing-undo", str(height))
            for key_hash, balance, nonce in _decode_undo(data):
                self._db.set_account(key_hash, balance, nonce)
            self._db.remove_active(height)
            return block_hash

    # ---------------------------------------------------------------- helpers
    def _check_shape(self, block: Block) -> None:
        txs = block.transactions
        if not txs:
            raise ChainStateError("no-transactions")
        if not txs[0].is_coinbase:
            raise ChainStateError("first-tx-not-coinbase")
        if any(tx.is_coinbase for tx in txs[1:]):
            raise ChainStateError("multiple-coinbase")

    def _check_stateless(self, tx: Transaction) -> None:
        try:
            tx.validate_stateless(self._params)
        except TransactionError as exc:
            raise ChainStateError("bad-tx", str(exc)) from exc

    def _credit(self, overlay: _Overlay, key_hash: bytes, amount: int) -> None:
        balance, nonce = overlay.get(key_hash)
        if balance + amount > self._params.max_supply:
            raise ChainStateError("balance-overflow")
        overlay.set(key_hash, balance + amount, nonce)

    def _apply_transfer(self, tx: Transaction, overlay: _Overlay) -> int:
        """Apply one transfer to the overlay and return its fee."""
        self._check_stateless(tx)
        sender = tx.sender_key_hash
        balance, nonce = overlay.get(sender)
        if tx.nonce != nonce:
            raise ChainStateError("bad-nonce", f"expected {nonce}, got {tx.nonce}")
        if balance < tx.amount + tx.fee:
            raise ChainStateError("insufficient-funds")
        overlay.set(sender, balance - tx.amount - tx.fee, nonce + 1)
        self._credit(overlay, tx.recipient, tx.amount)
        return tx.fee