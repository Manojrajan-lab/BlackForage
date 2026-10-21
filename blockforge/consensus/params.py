"""Consensus parameters for BlockForge.

Every value here is consensus-critical: two nodes that disagree on any of
them will fork. Non-consensus settings (ports, paths, API keys) live in
blockforge/config.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

COIN = 100_000_000  # 1 BF = 10^8 base units ("forge")
MAX_UINT64 = (1 << 64) - 1


class Network(str, Enum):
    DEV = "dev"
    TESTNET = "testnet"
    MAINNET = "mainnet"


@dataclass(frozen=True)
class ConsensusParams:
    network: Network
    chain_id: int
    address_prefix: str

    # Timing / difficulty
    target_block_time: int          # seconds
    retarget_interval: int          # blocks
    retarget_clamp: int             # max up/down adjustment factor
    initial_bits: int               # compact target of genesis
    max_target: int                 # easiest target allowed (pow limit)

    # Issuance
    initial_reward: int             # base units
    halving_interval: int           # blocks
    max_supply: int                 # base units, hard cap
    coinbase_maturity: int          # blocks before coinbase spendable

    # Limits
    max_block_bytes: int
    max_block_txs: int
    max_tx_bytes: int
    min_fee: int                    # base units
    max_future_drift: int           # seconds
    median_time_span: int           # blocks used for median-time-past

    # Genesis (fixed so the genesis hash is deterministic)
    genesis_timestamp: int
    genesis_message: bytes
    genesis_nonce: int              # filled by tools/mine_genesis after first computation

    def __post_init__(self) -> None:
        if self.retarget_interval < 2:
            raise ValueError("retarget_interval must be >= 2")
        if self.halving_interval < 1:
            raise ValueError("halving_interval must be >= 1")
        if self.initial_reward <= 0 or self.initial_reward > self.max_supply:
            raise ValueError("invalid initial_reward")
        if not (0 < self.max_target < (1 << 256)):
            raise ValueError("invalid max_target")
        if self.max_supply > MAX_UINT64:
            raise ValueError("max_supply exceeds uint64")

    def max_issuable(self) -> int:
        """Total subsidy summed over all halvings, capped at max_supply.

        Used by tests to prove the schedule can never exceed the cap.
        """
        total, reward, height_span = 0, self.initial_reward, self.halving_interval
        while reward > 0:
            total += reward * height_span
            reward //= 2
        return min(total, self.max_supply)


def _bits_to_target(bits: int) -> int:
    exponent = bits >> 24
    mantissa = bits & 0x007FFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


_MAINNET_BITS = 0x1F00FFFF
_TESTNET_BITS = 0x1F0FFFFF
_DEV_BITS = 0x2000FFFF

MAINNET = ConsensusParams(
    network=Network.MAINNET,
    chain_id=1,
    address_prefix="BF",
    target_block_time=120,
    retarget_interval=144,
    retarget_clamp=4,
    initial_bits=_MAINNET_BITS,
    max_target=_bits_to_target(_DEV_BITS),
    initial_reward=50 * COIN,
    halving_interval=1_050_000,
    max_supply=105_000_000 * COIN,
    coinbase_maturity=100,
    max_block_bytes=1_000_000,
    max_block_txs=5_000,
    max_tx_bytes=100_000,
    min_fee=1_000,
    max_future_drift=2 * 60 * 60,
    median_time_span=11,
    genesis_timestamp=1_798_761_600,  # 2027-01-01T00:00:00Z
    genesis_message=b"BlockForge mainnet genesis",
    genesis_nonce=0,
)

TESTNET = ConsensusParams(
    network=Network.TESTNET,
    chain_id=2,
    address_prefix="BF",
    target_block_time=60,
    retarget_interval=60,
    retarget_clamp=4,
    initial_bits=_TESTNET_BITS,
    max_target=_bits_to_target(_DEV_BITS),
    initial_reward=50 * COIN,
    halving_interval=10_000,
    max_supply=105_000_000 * COIN,
    coinbase_maturity=10,
    max_block_bytes=1_000_000,
    max_block_txs=5_000,
    max_tx_bytes=100_000,
    min_fee=100,
    max_future_drift=2 * 60 * 60,
    median_time_span=11,
    genesis_timestamp=1_790_000_000,
    genesis_message=b"BlockForge testnet genesis",
    genesis_nonce=0,
)

DEV = ConsensusParams(
    network=Network.DEV,
    chain_id=1337,
    address_prefix="BF",
    target_block_time=1,
    retarget_interval=10,
    retarget_clamp=4,
    initial_bits=_DEV_BITS,
    max_target=_bits_to_target(_DEV_BITS),
    initial_reward=50 * COIN,
    halving_interval=100,
    max_supply=105_000_000 * COIN,
    coinbase_maturity=2,
    max_block_bytes=1_000_000,
    max_block_txs=5_000,
    max_tx_bytes=100_000,
    min_fee=1,
    max_future_drift=2 * 60 * 60,
    median_time_span=11,
    genesis_timestamp=1_700_000_000,
    genesis_message=b"BlockForge dev genesis",
    genesis_nonce=0,
)

_BY_NETWORK = {
    Network.MAINNET: MAINNET,
    Network.TESTNET: TESTNET,
    Network.DEV: DEV,
}


def get_params(network: Network | str) -> ConsensusParams:
    """Return consensus parameters for a network name."""
    return _BY_NETWORK[Network(network)]