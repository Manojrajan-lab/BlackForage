"""Request/response models and serializers for the HTTP API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from blockforge.consensus.params import ConsensusParams
from blockforge.core import crypto
from blockforge.core.amounts import format_amount
from blockforge.core.block import Block
from blockforge.core.transaction import Transaction

HEX64 = r"^[0-9a-f]{64}$"
LOWER_HEX = r"^(?:[0-9a-f]{2})+$"


# ------------------------------------------------------------------- requests
class SubmitTxIn(BaseModel):
    hex: str = Field(..., pattern=LOWER_HEX, max_length=2 * 100_000,
                     description="canonical serialized transaction, lowercase hex")


class SubmitBlockIn(BaseModel):
    hex: str = Field(..., pattern=LOWER_HEX, max_length=2 * 1_000_000,
                     description="canonical serialized block, lowercase hex")


class MiningStartIn(BaseModel):
    address: str = Field(..., min_length=3, max_length=100)


class ConnectIn(BaseModel):
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(..., ge=1, le=65535)


# ------------------------------------------------------------------ responses
class SubmitTxOut(BaseModel):
    txid: str


class AccountOut(BaseModel):
    address: str
    balance: int
    balance_formatted: str
    spendable: int
    spendable_formatted: str
    nonce: int
    next_nonce: int


class StatusOut(BaseModel):
    network: str
    chain_id: int
    height: int
    tip: str
    chainwork: str
    mempool_txs: int
    mempool_bytes: int
    total_supply: int
    total_supply_formatted: str
    mining: bool
    peers: int


# ---------------------------------------------------------------- serializers
def tx_to_dict(tx: Transaction, params: ConsensusParams,
               height: Optional[int] = None, position: Optional[int] = None,
               confirmed: Optional[bool] = None) -> Dict[str, Any]:
    prefix = params.address_prefix
    sender = None if tx.is_coinbase else crypto.key_hash_to_address(tx.sender_key_hash, prefix)
    return {
        "txid": tx.txid_hex,
        "kind": "coinbase" if tx.is_coinbase else "transfer",
        "sender": sender,
        "recipient": crypto.key_hash_to_address(tx.recipient, prefix),
        "amount": tx.amount,
        "amount_formatted": format_amount(tx.amount),
        "fee": tx.fee,
        "fee_formatted": format_amount(tx.fee),
        "nonce": tx.nonce,
        "memo_hex": tx.memo.hex(),
        "size": tx.size,
        "block_height": height,
        "position": position,
        "confirmed": (height is not None) if confirmed is None else confirmed,
    }


def block_to_dict(block: Block, params: ConsensusParams, full: bool = True) -> Dict[str, Any]:
    h = block.header
    out: Dict[str, Any] = {
        "hash": block.hash_hex,
        "height": h.height,
        "version": h.version,
        "prev_hash": h.prev_hash.hex(),
        "merkle_root": h.merkle_root.hex(),
        "timestamp": h.timestamp,
        "bits": h.bits,
        "nonce": h.nonce,
        "tx_count": len(block.transactions),
        "size": block.size,
    }
    if full:
        out["transactions"] = [tx_to_dict(tx, params, h.height, i, True)
                               for i, tx in enumerate(block.transactions)]
    return out