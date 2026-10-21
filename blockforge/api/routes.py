"""HTTP routes. Endpoints are plain `def`, so FastAPI runs them in a worker
thread and the blocking node/database calls never stall the event loop."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path, Query, Request

from blockforge.api.errors import ApiError
from blockforge.api.schemas import (
    HEX64,
    AccountOut,
    ConnectIn,
    MiningStartIn,
    StatusOut,
    SubmitBlockIn,
    SubmitTxIn,
    SubmitTxOut,
    block_to_dict,
    tx_to_dict,
)
from blockforge.api.security import require_admin, tx_rate_limit
from blockforge.consensus.validation import ValidationError
from blockforge.core import crypto
from blockforge.core.amounts import format_amount
from blockforge.core.block import Block, BlockFormatError
from blockforge.core.transaction import Transaction, TransactionError
from blockforge.mempool.mempool import MempoolError
from blockforge.node.fork_choice import ForkChoiceError
from blockforge.node.node import Node
from blockforge.storage.chainstate import ChainStateError

router = APIRouter()

MAX_PAGE = 100


def _node(request: Request) -> Node:
    return request.app.state.node


def _key_hash(request: Request, address: str) -> bytes:
    try:
        return crypto.address_to_key_hash(address, _node(request).params.address_prefix)
    except crypto.CryptoError as exc:
        raise ApiError(400, "bad-address", str(exc)) from exc


# ---------------------------------------------------------------------- health
@router.get("/health", tags=["meta"])
def health(request: Request) -> Dict[str, Any]:
    tip = _node(request).tip()
    return {"status": "ok", "height": tip[0]}


@router.get("/v1/status", response_model=StatusOut, tags=["chain"])
def status(request: Request) -> Dict[str, Any]:
    node = _node(request)
    data = node.status()
    p2p = request.app.state.p2p
    data["chainwork"] = str(data["chainwork"])
    data["total_supply_formatted"] = format_amount(data["total_supply"])
    data["peers"] = p2p.peer_count() if p2p is not None else 0
    return data


# ---------------------------------------------------------------------- blocks
@router.get("/v1/blocks", tags=["chain"])
def list_blocks(
    request: Request,
    limit: int = Query(20, ge=1, le=MAX_PAGE),
    before: Optional[int] = Query(None, ge=0, description="return blocks below this height"),
) -> List[Dict[str, Any]]:
    node = _node(request)
    top = node.tip()[0]
    start = top if before is None else min(before - 1, top)
    out: List[Dict[str, Any]] = []
    height = start
    while height >= 0 and len(out) < limit:
        block = node.get_block_by_height(height)
        if block is not None:
            out.append(block_to_dict(block, node.params, full=False))
        height -= 1
    return out


@router.get("/v1/blocks/height/{height}", tags=["chain"])
def block_by_height(request: Request, height: int = Path(..., ge=0)) -> Dict[str, Any]:
    node = _node(request)
    block = node.get_block_by_height(height)
    if block is None:
        raise ApiError(404, "not-found", "no block at that height")
    return block_to_dict(block, node.params)


@router.get("/v1/blocks/{block_hash}", tags=["chain"])
def block_by_hash(request: Request, block_hash: str = Path(..., pattern=HEX64)) -> Dict[str, Any]:
    node = _node(request)
    block = node.get_block_by_hash(bytes.fromhex(block_hash))
    if block is None:
        raise ApiError(404, "not-found", "unknown block")
    return block_to_dict(block, node.params)


@router.post("/v1/blocks", tags=["admin"], dependencies=[Depends(require_admin)])
def submit_block(request: Request, body: SubmitBlockIn) -> Dict[str, Any]:
    node = _node(request)
    try:
        block = Block.deserialize(bytes.fromhex(body.hex), Transaction.deserialize)
        outcomes = node.submit_block(block)
    except (BlockFormatError, ValidationError, ChainStateError, ForkChoiceError) as exc:
        raise ApiError(400, "invalid-block", str(exc)) from exc
    return {"hash": block.hash_hex, "status": outcomes[0].status.value}


# ---------------------------------------------------------------- transactions
@router.post("/v1/transactions", response_model=SubmitTxOut, status_code=201,
             tags=["transactions"], dependencies=[Depends(tx_rate_limit)])
def submit_transaction(request: Request, body: SubmitTxIn) -> Dict[str, str]:
    node = _node(request)
    try:
        tx = Transaction.deserialize(bytes.fromhex(body.hex))
        txid = node.submit_transaction(tx)
    except TransactionError as exc:
        raise ApiError(400, "invalid-transaction", str(exc)) from exc
    except MempoolError as exc:
        code = 409 if exc.code in ("duplicate", "stale-nonce", "nonce-gap",
                                   "fee-too-low-to-replace") else 400
        raise ApiError(code, f"mempool-{exc.code}", str(exc)) from exc
    return {"txid": txid.hex()}


@router.get("/v1/transactions/{txid}", tags=["transactions"])
def get_transaction(request: Request, txid: str = Path(..., pattern=HEX64)) -> Dict[str, Any]:
    node = _node(request)
    found = node.get_transaction(bytes.fromhex(txid))
    if found is None:
        raise ApiError(404, "not-found", "unknown transaction")
    return tx_to_dict(found["tx"], node.params, found["height"], found["position"],
                      found["confirmed"])


@router.get("/v1/mempool", tags=["transactions"])
def mempool(request: Request, limit: int = Query(50, ge=1, le=MAX_PAGE)) -> Dict[str, Any]:
    node = _node(request)
    pool = node.mempool
    txs, fees = pool.select_for_block(node.params.max_block_bytes, limit)
    return {
        "count": len(pool),
        "bytes": pool.total_bytes(),
        "next_block_fees": fees,
        "transactions": [tx_to_dict(t, node.params, None, None, False) for t in txs],
    }


# -------------------------------------------------------------------- accounts
@router.get("/v1/accounts/{address}", response_model=AccountOut, tags=["accounts"])
def account(request: Request, address: str = Path(..., max_length=100)) -> Dict[str, Any]:
    node = _node(request)
    data = node.get_account(_key_hash(request, address))
    return {
        "address": address,
        "balance": data["balance"],
        "balance_formatted": format_amount(data["balance"]),
        "spendable": data["spendable"],
        "spendable_formatted": format_amount(data["spendable"]),
        "nonce": data["nonce"],
        "next_nonce": data["next_nonce"],
    }


@router.get("/v1/accounts/{address}/transactions", tags=["accounts"])
def account_transactions(
    request: Request,
    address: str = Path(..., max_length=100),
    limit: int = Query(25, ge=1, le=MAX_PAGE),
    before: Optional[int] = Query(None, ge=0, description="only blocks below this height"),
) -> List[Dict[str, Any]]:
    node = _node(request)
    rows = node.db.get_address_txs(_key_hash(request, address), limit, before)
    out: List[Dict[str, Any]] = []
    for txid, _height, _position in rows:
        found = node.get_transaction(txid)
        if found is not None:
            out.append(tx_to_dict(found["tx"], node.params, found["height"],
                                  found["position"], found["confirmed"]))
    return out


# --------------------------------------------------------------------- network
@router.get("/v1/network/peers", tags=["network"])
def peers(request: Request) -> Dict[str, Any]:
    p2p = request.app.state.p2p
    if p2p is None:
        return {"stats": {"peers": 0}, "peers": []}
    return {"stats": p2p.stats(), "peers": p2p.peers_info()}


@router.post("/v1/network/connect", tags=["admin"], dependencies=[Depends(require_admin)])
async def connect_peer(request: Request, body: ConnectIn) -> Dict[str, str]:
    p2p = request.app.state.p2p
    if p2p is None:
        raise ApiError(503, "p2p-disabled", "P2P networking is disabled")
    await p2p.connect_to(body.host, body.port)
    return {"status": "dialing"}


# ---------------------------------------------------------------------- mining
@router.get("/v1/mining", tags=["mining"])
def mining_status(request: Request) -> Dict[str, bool]:
    return {"mining": _node(request).is_mining()}


@router.post("/v1/mining/start", tags=["admin"], dependencies=[Depends(require_admin)])
def mining_start(request: Request, body: MiningStartIn) -> Dict[str, Any]:
    node = _node(request)
    node.start_mining(_key_hash(request, body.address))
    return {"mining": True, "address": body.address}


@router.post("/v1/mining/stop", tags=["admin"], dependencies=[Depends(require_admin)])
def mining_stop(request: Request) -> Dict[str, bool]:
    _node(request).stop_mining()
    return {"mining": False}