import type { NetworkName } from "@/config";

/**
 * Consensus values the signer needs. The backend does NOT expose these over HTTP
 * (only network + chain_id in /v1/status), so they are copied from
 * blockforge/consensus/params.py and must be kept in sync. The wallet refuses to
 * sign when /v1/status reports a different network or chain_id.
 */
export interface ChainParams {
  network: NetworkName;
  chainId: number;
  addressPrefix: string;
  minFee: bigint;
  coinbaseMaturity: number;
  targetBlockTime: number;
  maxMemoBytes: number;
}

export const CHAIN_PARAMS: Record<NetworkName, ChainParams> = {
  dev: { network: "dev", chainId: 1337, addressPrefix: "BF", minFee: 1n, coinbaseMaturity: 2, targetBlockTime: 1, maxMemoBytes: 100 },
  testnet: { network: "testnet", chainId: 2, addressPrefix: "BF", minFee: 100n, coinbaseMaturity: 10, targetBlockTime: 60, maxMemoBytes: 100 },
  mainnet: { network: "mainnet", chainId: 1, addressPrefix: "BF", minFee: 1000n, coinbaseMaturity: 100, targetBlockTime: 120, maxMemoBytes: 100 },
};

/** Compact "bits" -> 256-bit target (mirrors consensus/pow.py; sign bit => invalid => 0). */
export function bitsToTarget(bits: number): bigint {
  if (bits < 0 || bits > 0xffffffff || (bits & 0x00800000) !== 0) return 0n;
  const exponent = bits >>> 24;
  const mantissa = BigInt(bits & 0x007fffff);
  return exponent <= 3 ? mantissa >> BigInt(8 * (3 - exponent)) : mantissa << BigInt(8 * (exponent - 3));
}

/** All networks share the same pow limit: bits_to_target(0x2000FFFF). */
export const POW_LIMIT = bitsToTarget(0x2000ffff);

/** Expected hashes for one block: 2^256 / (target + 1). */
export function workFromBits(bits: number): bigint {
  return (1n << 256n) / (bitsToTarget(bits) + 1n);
}

/** Difficulty relative to the pow limit (1.0 = easiest allowed). */
export function difficultyFromBits(bits: number): number {
  const t = bitsToTarget(bits);
  if (t === 0n) return Number.NaN;
  return Number((POW_LIMIT * 1_000_000n) / t) / 1_000_000;
}
