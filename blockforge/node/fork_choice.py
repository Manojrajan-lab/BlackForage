"""Block acceptance and best-chain selection.

Flow for every incoming block:
  1. stateless checks (structure, tx signatures) and header checks against its
     parent (difficulty, median-time-past, PoW) -- works for side branches too
  2. store it; if it extends the tip, apply it
  3. if it sits on a side branch whose cumulative work exceeds the tip's,
     reorganize: revert to the fork point, apply the new branch
  4. a failed apply rolls the whole reorg back (one DB transaction), marks the
     bad block and its descendants invalid, and re-raises

Ties go to the chain seen first (strictly greater work is required to switch).
Blocks whose parent is unknown are held in a bounded orphan pool and retried
when the parent arrives.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Set

from blockforge.consensus.difficulty import is_retarget_height, next_required_bits
from blockforge.consensus.params import ConsensusParams
from blockforge.consensus.validation import (
    ValidationError,
    median_time_past,
    validate_block_structure,
    validate_header,
)
from blockforge.core.block import HEADER_SIZE, Block, BlockHeader
from blockforge.core.genesis import build_genesis_block, verify_genesis
from blockforge.core.transaction import Transaction, TransactionError
from blockforge.storage.chainstate import ChainState, ChainStateError


class ForkChoiceError(ValueError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


class Status(str, Enum):
    EXTENDED = "extended"    # new tip on the active chain
    REORG = "reorg"          # switched to a heavier branch
    SIDE = "side"            # stored on a branch that is not (yet) the best
    DUPLICATE = "duplicate"  # already known
    ORPHAN = "orphan"        # parent unknown; held for later


@dataclass
class Outcome:
    status: Status
    block_hash: bytes
    applied: List[Block] = field(default_factory=list)    # newly active blocks, oldest first
    reverted: List[Block] = field(default_factory=list)   # no-longer-active blocks, oldest first


class _OrphanPool:
    def __init__(self, max_blocks: int = 200) -> None:
        self._max = max_blocks
        self._by_hash: "OrderedDict[bytes, Block]" = OrderedDict()
        self._by_parent: Dict[bytes, List[bytes]] = {}

    def __contains__(self, block_hash: bytes) -> bool:
        return block_hash in self._by_hash

    def add(self, block: Block) -> None:
        h = block.hash
        if h in self._by_hash:
            return
        while len(self._by_hash) >= self._max:
            old_hash, old = self._by_hash.popitem(last=False)
            siblings = self._by_parent.get(old.prev_hash, [])
            if old_hash in siblings:
                siblings.remove(old_hash)
            if not siblings:
                self._by_parent.pop(old.prev_hash, None)
        self._by_hash[h] = block
        self._by_parent.setdefault(block.prev_hash, []).append(h)

    def pop_children(self, parent_hash: bytes) -> List[Block]:
        children = []
        for h in self._by_parent.pop(parent_hash, []):
            blk = self._by_hash.pop(h, None)
            if blk is not None:
                children.append(blk)
        return children


class ForkChoice:
    def __init__(
        self,
        chainstate: ChainState,
        params: ConsensusParams,
        clock: Callable[[], float] = time.time,
        max_reorg_depth: int = 288,
    ) -> None:
        self._state = chainstate
        self._db = chainstate.db
        self._params = params
        self._clock = clock
        self._max_reorg_depth = max_reorg_depth
        self._lock = threading.RLock()
        self._invalid: Set[bytes] = set()
        self._orphans = _OrphanPool()

    # ---------------------------------------------------------------- startup
    def initialize(self) -> None:
        """Create the genesis block on an empty database, or verify the stored one."""
        with self._lock:
            genesis = build_genesis_block(self._params)
            if self._db.get_tip() is None:
                if not verify_genesis(genesis, self._params):
                    raise ForkChoiceError("bad-genesis")
                self._state.apply_block(genesis)
                return
            if self._db.get_active_hash(0) != genesis.hash:
                raise ForkChoiceError("genesis-mismatch", "database belongs to another network")

    # ----------------------------------------------------------------- public
    def process_block(self, block: Block) -> List[Outcome]:
        """Handle one block (plus any orphans it unlocks). Raises on an invalid block."""
        with self._lock:
            first = self._process_one(block)
            results = [first]
            if first.status in (Status.EXTENDED, Status.REORG, Status.SIDE):
                queue = [block.hash]
                while queue:
                    parent = queue.pop(0)
                    for child in self._orphans.pop_children(parent):
                        try:
                            out = self._process_one(child)
                        except (ValidationError, ChainStateError, ForkChoiceError):
                            continue  # a bad orphan must not block its siblings
                        results.append(out)
                        if out.status in (Status.EXTENDED, Status.REORG, Status.SIDE):
                            queue.append(child.hash)
            return results

    def is_known(self, block_hash: bytes) -> bool:
        with self._lock:
            return self._db.has_block(block_hash) or block_hash in self._orphans

    def is_invalid(self, block_hash: bytes) -> bool:
        with self._lock:
            return block_hash in self._invalid

    def block_locator(self) -> List[bytes]:
        """Active-chain hashes, dense near the tip then exponentially sparser, ending at genesis."""
        with self._lock:
            tip = self._db.get_tip()
            if tip is None:
                return []
            hashes: List[bytes] = []
            height, step, last_height = tip[0], 1, tip[0]
            while height >= 0:
                hashes.append(self._db.get_active_hash(height))
                last_height = height
                if len(hashes) >= 10:
                    step *= 2
                height -= step
            if last_height != 0:
                hashes.append(self._db.get_active_hash(0))
            return hashes

    def find_common_height(self, locator: List[bytes]) -> Optional[int]:
        """Height of the first locator hash that is on our active chain."""
        with self._lock:
            for h in locator[:64]:
                if self._db.is_active(h):
                    row = self._db.get_block_by_hash(h)
                    if row is not None:
                        return row[0]
            return None
    def required_bits_for_child(self, parent_hash: bytes) -> int:
        """Bits a block built on `parent_hash` must use."""
        with self._lock:
            parent = self._header(parent_hash)
            return self._expected_bits(parent_hash, parent, parent.height + 1)

    def mtp_of(self, tip_hash: bytes) -> int:
        """Median-time-past of the chain ending at `tip_hash`."""
        with self._lock:
            return median_time_past(self._recent_timestamps(tip_hash),
                                    self._params.median_time_span)

    # ---------------------------------------------------------------- internals
    def _process_one(self, block: Block) -> Outcome:
        h = block.hash
        if h in self._invalid:
            raise ForkChoiceError("known-invalid")
        if self._db.has_block(h):
            return Outcome(Status.DUPLICATE, h)
        if block.prev_hash in self._invalid:
            self._invalid.add(h)
            raise ForkChoiceError("invalid-parent")
        if block.height == 0:
            raise ForkChoiceError("unexpected-genesis")

        # Context-free checks first (cheap to expensive).
        validate_block_structure(self._params, block)
        for tx in block.transactions:
            try:
                tx.validate_stateless(self._params)
            except TransactionError as exc:
                raise ValidationError("bad-tx", str(exc)) from exc

        parent_row = self._db.get_block_by_hash(block.prev_hash)
        if parent_row is None:
            self._orphans.add(block)
            return Outcome(Status.ORPHAN, h)

        parent = BlockHeader.deserialize(parent_row[3][:HEADER_SIZE])
        expected_bits = self._expected_bits(block.prev_hash, parent, block.height)
        mtp = median_time_past(self._recent_timestamps(block.prev_hash),
                               self._params.median_time_span)
        validate_header(self._params, block.header, parent, expected_bits, mtp,
                        int(self._clock()))

        tip = self._db.get_tip()
        if tip is None:
            raise ForkChoiceError("no-genesis", "call initialize() first")

        chainwork = self._state.store_block(block)
        if block.prev_hash == tip[1]:
            try:
                self._state.apply_block(block)
            except ChainStateError:
                self._reject([h])
                raise
            return Outcome(Status.EXTENDED, h, applied=[block])
        if chainwork > tip[2]:
            return self._reorganize(block, tip)
        return Outcome(Status.SIDE, h)

    def _reorganize(self, new_block: Block, tip) -> Outcome:
        tip_height = tip[0]
        branch = [new_block]
        cursor = new_block.prev_hash
        while not self._db.is_active(cursor):
            blk = self._state.get_block(cursor)
            if blk is None:
                raise ForkChoiceError("missing-ancestor")
            branch.append(blk)
            cursor = blk.prev_hash
        branch.reverse()

        fork_height = self._db.get_block_by_hash(cursor)[0]
        depth = tip_height - fork_height
        if depth > self._max_reorg_depth:
            return Outcome(Status.SIDE, new_block.hash)  # keep stored, refuse to switch

        reverted: List[Block] = []
        failed_index: Optional[int] = None
        try:
            with self._db.atomic():  # any failure restores the old chain exactly
                for _ in range(depth):
                    old = self._state.get_block(self._db.get_tip()[1])
                    self._state.revert_tip()
                    reverted.append(old)
                for i, blk in enumerate(branch):
                    failed_index = i
                    self._state.apply_block(blk)
                failed_index = None
        except ChainStateError:
            if failed_index is not None:
                self._reject([b.hash for b in branch[failed_index:]])
            raise
        reverted.reverse()
        return Outcome(Status.REORG, new_block.hash, applied=branch, reverted=reverted)

    def _reject(self, hashes: List[bytes]) -> None:
        for h in hashes:
            self._invalid.add(h)
            self._db.delete_block(h)

    # ----------------------------------------------------------- chain context
    def _header(self, block_hash: bytes) -> BlockHeader:
        row = self._db.get_block_by_hash(block_hash)
        if row is None:
            raise ForkChoiceError("missing-ancestor")
        return BlockHeader.deserialize(row[3][:HEADER_SIZE])

    def _ancestor_hash(self, from_hash: bytes, from_height: int, target_height: int) -> bytes:
        cur, h = from_hash, from_height
        while h > target_height:
            if self._db.is_active(cur):
                return self._db.get_active_hash(target_height)
            cur = self._header(cur).prev_hash
            h -= 1
        return cur

    def _recent_timestamps(self, tip_hash: bytes) -> List[int]:
        out: List[int] = []
        cur = tip_hash
        for _ in range(self._params.median_time_span):
            hdr = self._header(cur)
            out.append(hdr.timestamp)
            if hdr.height == 0:
                break
            cur = hdr.prev_hash
        out.reverse()
        return out

    def _expected_bits(self, parent_hash: bytes, parent: BlockHeader, height: int) -> int:
        if not is_retarget_height(self._params, height):
            return next_required_bits(self._params, height, prev_bits=parent.bits)
        first_hash = self._ancestor_hash(parent_hash, parent.height,
                                         height - self._params.retarget_interval)
        first = self._header(first_hash)
        return next_required_bits(self._params, height, parent.bits,
                                  first.timestamp, parent.timestamp)