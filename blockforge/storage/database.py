"""SQLite persistence for BlockForge (account model).

Tables:
  blocks        every known block (main chain and side branches), keyed by hash
  active_chain  height -> hash of the current best chain
  accounts      key_hash -> (balance, nonce); zero/zero rows are not stored
  tx_index      txid -> (height, position) for the active chain
  address_txs   per-address transaction history for the active chain
  undo          per-height blob used to roll back state during reorgs
  meta          small key/value settings

All amounts are integer base units (SQLite signed 64-bit is far above max supply).
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator, List, Optional, Tuple

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS blocks (
    hash      BLOB    PRIMARY KEY,
    height    INTEGER NOT NULL,
    prev_hash BLOB    NOT NULL,
    chainwork TEXT    NOT NULL,
    data      BLOB    NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_blocks_height ON blocks(height);
CREATE INDEX IF NOT EXISTS idx_blocks_prev   ON blocks(prev_hash);

CREATE TABLE IF NOT EXISTS active_chain (
    height INTEGER PRIMARY KEY,
    hash   BLOB    NOT NULL UNIQUE REFERENCES blocks(hash)
);

CREATE TABLE IF NOT EXISTS accounts (
    key_hash BLOB    PRIMARY KEY,
    balance  INTEGER NOT NULL CHECK (balance >= 0),
    nonce    INTEGER NOT NULL CHECK (nonce >= 0)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS tx_index (
    txid     BLOB    PRIMARY KEY,
    height   INTEGER NOT NULL,
    position INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_tx_height ON tx_index(height);

CREATE TABLE IF NOT EXISTS address_txs (
    key_hash BLOB    NOT NULL,
    txid     BLOB    NOT NULL,
    height   INTEGER NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (key_hash, txid)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_addr_order ON address_txs(key_hash, height, position);
CREATE INDEX IF NOT EXISTS idx_addr_height ON address_txs(height);

CREATE TABLE IF NOT EXISTS undo (
    height INTEGER PRIMARY KEY,
    data   BLOB    NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class DatabaseError(RuntimeError):
    """Raised for incompatible or corrupt database files."""


class Database:
    def __init__(self, path: str = "blockforge.db") -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._depth = 0
        self._init_schema()

    def _init_schema(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise DatabaseError(f"unsupported database schema version {version}")
        if version == 0:
            legacy = self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='utxos'"
            ).fetchone()
            if legacy:
                raise DatabaseError("legacy UTXO-schema database found; delete it and resync")
            self._conn.executescript(SCHEMA)
            self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def atomic(self) -> Iterator[None]:
        """Atomic write scope. Nested calls use savepoints."""
        with self._lock:
            outer = self._depth == 0
            name = f"sp{self._depth}"
            self._conn.execute("BEGIN IMMEDIATE" if outer else f"SAVEPOINT {name}")
            self._depth += 1
            try:
                yield
            except BaseException:
                self._depth -= 1
                if outer:
                    self._conn.execute("ROLLBACK")
                else:
                    self._conn.execute(f"ROLLBACK TO {name}")
                    self._conn.execute(f"RELEASE {name}")
                raise
            else:
                self._depth -= 1
                self._conn.execute("COMMIT" if outer else f"RELEASE {name}")

    # ------------------------------------------------------------------ meta
    def get_meta(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # ---------------------------------------------------------------- blocks
    def put_block(self, block_hash: bytes, height: int, prev_hash: bytes,
                  chainwork: int, data: bytes) -> None:
        """Store a block (any branch). Idempotent on the hash."""
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO blocks(hash, height, prev_hash, chainwork, data) "
                "VALUES(?, ?, ?, ?, ?)",
                (block_hash, height, prev_hash, format(chainwork, "x"), data),
            )

    def has_block(self, block_hash: bytes) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM blocks WHERE hash=?", (block_hash,)
            ).fetchone() is not None

    def get_block_by_hash(self, block_hash: bytes) -> Optional[Tuple[int, bytes, int, bytes]]:
        """Returns (height, prev_hash, chainwork, data) or None."""
        with self._lock:
            r = self._conn.execute(
                "SELECT height, prev_hash, chainwork, data FROM blocks WHERE hash=?",
                (block_hash,),
            ).fetchone()
            if r is None:
                return None
            return (r["height"], bytes(r["prev_hash"]), int(r["chainwork"], 16), bytes(r["data"]))

    def get_children(self, block_hash: bytes) -> List[bytes]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT hash FROM blocks WHERE prev_hash=?", (block_hash,)
            ).fetchall()
            return [bytes(r["hash"]) for r in rows]

    def delete_block(self, block_hash: bytes) -> None:
        """Remove a stored block. Must not be on the active chain."""
        with self._lock:
            self._conn.execute("DELETE FROM blocks WHERE hash=?", (block_hash,))

    # ---------------------------------------------------------- active chain
    def set_active(self, height: int, block_hash: bytes) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO active_chain(height, hash) VALUES(?, ?)",
                (height, block_hash),
            )

    def remove_active(self, height: int) -> None:
        """Drop a height from the active chain along with its tx index and undo data."""
        with self._lock:
            self._conn.execute("DELETE FROM active_chain WHERE height=?", (height,))
            self._conn.execute("DELETE FROM tx_index WHERE height=?", (height,))
            self._conn.execute("DELETE FROM address_txs WHERE height=?", (height,))
            self._conn.execute("DELETE FROM undo WHERE height=?", (height,))

    def get_active_hash(self, height: int) -> Optional[bytes]:
        with self._lock:
            r = self._conn.execute(
                "SELECT hash FROM active_chain WHERE height=?", (height,)
            ).fetchone()
            return bytes(r["hash"]) if r else None

    def is_active(self, block_hash: bytes) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM active_chain WHERE hash=?", (block_hash,)
            ).fetchone() is not None

    def get_tip(self) -> Optional[Tuple[int, bytes, int]]:
        """Returns (height, hash, chainwork) of the active chain tip, or None."""
        with self._lock:
            r = self._conn.execute(
                "SELECT a.height AS height, a.hash AS hash, b.chainwork AS chainwork "
                "FROM active_chain a JOIN blocks b ON b.hash = a.hash "
                "ORDER BY a.height DESC LIMIT 1"
            ).fetchone()
            if r is None:
                return None
            return (r["height"], bytes(r["hash"]), int(r["chainwork"], 16))

    def get_active_range(self, start: int, limit: int) -> List[Tuple[int, bytes, bytes]]:
        """Returns [(height, hash, data)] on the active chain for heights >= start."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT a.height AS height, a.hash AS hash, b.data AS data "
                "FROM active_chain a JOIN blocks b ON b.hash = a.hash "
                "WHERE a.height >= ? ORDER BY a.height ASC LIMIT ?",
                (start, limit),
            ).fetchall()
            return [(r["height"], bytes(r["hash"]), bytes(r["data"])) for r in rows]

    # -------------------------------------------------------------- accounts
    def get_account(self, key_hash: bytes) -> Tuple[int, int]:
        """Returns (balance, nonce); unknown accounts are (0, 0)."""
        with self._lock:
            r = self._conn.execute(
                "SELECT balance, nonce FROM accounts WHERE key_hash=?", (key_hash,)
            ).fetchone()
            return (r["balance"], r["nonce"]) if r else (0, 0)

    def set_account(self, key_hash: bytes, balance: int, nonce: int) -> None:
        """Upsert. A (0, 0) account is deleted so state is canonical and undo is exact."""
        if balance < 0 or nonce < 0:
            raise ValueError("balance and nonce must be non-negative")
        with self._lock:
            if balance == 0 and nonce == 0:
                self._conn.execute("DELETE FROM accounts WHERE key_hash=?", (key_hash,))
            else:
                self._conn.execute(
                    "INSERT INTO accounts(key_hash, balance, nonce) VALUES(?, ?, ?) "
                    "ON CONFLICT(key_hash) DO UPDATE SET "
                    "balance=excluded.balance, nonce=excluded.nonce",
                    (key_hash, balance, nonce),
                )

    def get_total_supply(self) -> int:
        with self._lock:
            r = self._conn.execute("SELECT COALESCE(SUM(balance), 0) AS s FROM accounts").fetchone()
            return int(r["s"])

    def count_accounts(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) AS c FROM accounts").fetchone()["c"])

    # -------------------------------------------------------------- tx index
    def index_tx(self, txid: bytes, height: int, position: int,
                 sender: Optional[bytes], recipient: bytes) -> None:
        """Index a confirmed tx by id and by each involved address (sender is None for coinbase)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO tx_index(txid, height, position) VALUES(?, ?, ?)",
                (txid, height, position),
            )
            for kh in {k for k in (sender, recipient) if k is not None}:
                self._conn.execute(
                    "INSERT INTO address_txs(key_hash, txid, height, position) "
                    "VALUES(?, ?, ?, ?)",
                    (kh, txid, height, position),
                )

    def get_tx_location(self, txid: bytes) -> Optional[Tuple[int, int]]:
        with self._lock:
            r = self._conn.execute(
                "SELECT height, position FROM tx_index WHERE txid=?", (txid,)
            ).fetchone()
            return (r["height"], r["position"]) if r else None

    def get_address_txs(self, key_hash: bytes, limit: int = 50,
                        before_height: Optional[int] = None) -> List[Tuple[bytes, int, int]]:
        """Newest-first [(txid, height, position)] for an address."""
        limit = max(1, min(limit, 1000))
        with self._lock:
            if before_height is None:
                rows = self._conn.execute(
                    "SELECT txid, height, position FROM address_txs WHERE key_hash=? "
                    "ORDER BY height DESC, position DESC LIMIT ?",
                    (key_hash, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT txid, height, position FROM address_txs "
                    "WHERE key_hash=? AND height<? "
                    "ORDER BY height DESC, position DESC LIMIT ?",
                    (key_hash, before_height, limit),
                ).fetchall()
            return [(bytes(r["txid"]), r["height"], r["position"]) for r in rows]

    # ------------------------------------------------------------------ undo
    def put_undo(self, height: int, data: bytes) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO undo(height, data) VALUES(?, ?)", (height, data)
            )

    def get_undo(self, height: int) -> Optional[bytes]:
        with self._lock:
            r = self._conn.execute("SELECT data FROM undo WHERE height=?", (height,)).fetchone()
            return bytes(r["data"]) if r else None