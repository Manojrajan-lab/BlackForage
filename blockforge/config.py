"""Runtime (non-consensus) settings, read from BLOCKFORGE_* environment variables.

Consensus-critical values live in blockforge/consensus/params.py.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Tuple

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from blockforge.consensus.params import ConsensusParams, Network, get_params


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BLOCKFORGE_", env_file=".env",
                                      extra="ignore")

    network: Network = Network.DEV
    data_dir: str = "./data"

    # HTTP API
    api_host: str = "127.0.0.1"
    api_port: int = Field(8000, ge=1, le=65535)
    api_key: str = ""                      # empty = admin endpoints disabled
    cors_origins: str = ""                 # comma separated, e.g. http://localhost:5173
    rate_limit_per_minute: int = Field(120, ge=1)
    tx_rate_limit_per_minute: int = Field(30, ge=1)
    max_body_bytes: int = Field(1_100_000, ge=1_000)

    # P2P
    p2p_enabled: bool = True
    p2p_host: str = "0.0.0.0"
    p2p_port: int = Field(9333, ge=0, le=65535)
    seeds: str = ""                        # comma separated host:port
    allow_private_peers: bool = False      # True for dev/test networks and docker
    max_inbound: int = Field(32, ge=0)
    max_outbound: int = Field(8, ge=0)

    # Mining
    mine: bool = False
    miner_address: str = ""

    # Logging
    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("api_key")
    @classmethod
    def _api_key_strength(cls, v: str) -> str:
        if v and len(v) < 16:
            raise ValueError("api_key must be at least 16 characters")
        return v

    @field_validator("log_level")
    @classmethod
    def _level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("invalid log level")
        return v

    # ------------------------------------------------------------------ derived
    @property
    def params(self) -> ConsensusParams:
        return get_params(self.network)

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, f"blockforge-{self.network.value}.db")

    @property
    def peers_file(self) -> str:
        return os.path.join(self.data_dir, f"peers-{self.network.value}.json")

    @property
    def cors_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def seed_list(self) -> List[Tuple[str, int]]:
        out: List[Tuple[str, int]] = []
        for item in self.seeds.split(","):
            item = item.strip()
            if not item:
                continue
            host, sep, port = item.rpartition(":")
            if not sep or not host or not port.isdigit() or not 1 <= int(port) <= 65535:
                raise ValueError(f"invalid seed {item!r}; expected host:port")
            out.append((host, int(port)))
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()