"""FastAPI application factory.

Run:  uvicorn --factory blockforge.api.app:create_app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from blockforge.api.errors import install_error_handlers
from blockforge.api.routes import router
from blockforge.api.security import RateLimiter, SecurityMiddleware
from blockforge.config import Settings, get_settings
from blockforge.core import crypto
from blockforge.logging_config import setup_logging
from blockforge.network.p2p import P2PNetwork
from blockforge.node.node import Node

log = logging.getLogger("blockforge.app")


def create_app(settings: Optional[Settings] = None, node: Optional[Node] = None,
               enable_p2p: Optional[bool] = None) -> FastAPI:
    """Build the app. Pass `node` to reuse an existing Node (the caller then
    owns its lifecycle); otherwise one is created from `settings`."""
    settings = settings or get_settings()
    setup_logging(settings.log_level, settings.log_json)
    owns_node = node is None
    if node is None:
        os.makedirs(settings.data_dir, exist_ok=True)
        node = Node(settings.params, settings.db_path)
    use_p2p = settings.p2p_enabled if enable_p2p is None else enable_p2p

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(node.start)
        p2p: Optional[P2PNetwork] = None
        if use_p2p:
            p2p = P2PNetwork(
                node, host=settings.p2p_host, port=settings.p2p_port,
                seeds=settings.seed_list, max_inbound=settings.max_inbound,
                max_outbound=settings.max_outbound,
                allow_private=settings.allow_private_peers,
                peers_file=settings.peers_file if owns_node else None,
            )
            await p2p.start()
        app.state.p2p = p2p
        if settings.mine:
            try:
                key_hash = crypto.address_to_key_hash(settings.miner_address,
                                                      settings.params.address_prefix)
            except crypto.CryptoError as exc:
                raise RuntimeError(f"BLOCKFORGE_MINER_ADDRESS invalid: {exc}") from exc
            node.start_mining(key_hash)
        try:
            yield
        finally:
            if p2p is not None:
                await p2p.stop()
            if owns_node:
                await asyncio.to_thread(node.stop)
            else:
                await asyncio.to_thread(node.stop_mining)

    app = FastAPI(title="BlockForge Node API", version="0.1.0", lifespan=lifespan,
                  docs_url="/docs", redoc_url=None)
    app.state.settings = settings
    app.state.node = node
    app.state.p2p = None
    app.state.tx_limiter = RateLimiter(settings.tx_rate_limit_per_minute)

    install_error_handlers(app)
    app.add_middleware(SecurityMiddleware,
                       limiter=RateLimiter(settings.rate_limit_per_minute),
                       max_body_bytes=settings.max_body_bytes)
    if settings.cors_list:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list,
                           allow_methods=["GET", "POST"],
                           allow_headers=["Content-Type", "X-API-Key"])
    app.include_router(router)
    return app