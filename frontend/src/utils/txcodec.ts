import { secp256k1 } from "@noble/curves/secp256k1";
import { sha256 } from "@noble/hashes/sha256";
import { bytesToHex, concat, hexToBytes } from "./bytes";
import type { ChainParams } from "./chain";

/** Canonical encoding from blockforge/core/serialization.py + core/transaction.py (big-endian, u32 length prefixes). */
const TX_VERSION = 1;
const KIND_TRANSFER = 1;
const SIGNING_DOMAIN = new TextEncoder().encode("BlockForge/tx/v1");
const KEYHASH_LEN = 20;
const CHECKSUM_LEN = 4;

export const sha256d = (data: Uint8Array): Uint8Array => sha256(sha256(data));

function uint(value: bigint | number, size: number): Uint8Array {
  let v = BigInt(value);
  if (v < 0n || v >= 1n << BigInt(8 * size)) throw new Error(`value out of range for uint${size * 8}`);
  const out = new Uint8Array(size);
  for (let i = size - 1; i >= 0; i--) { out[i] = Number(v & 0xffn); v >>= 8n; }
  return out;
}
const varBytes = (data: Uint8Array): Uint8Array => concat(uint(data.length, 4), data);

export function publicKeyOf(secret: Uint8Array): Uint8Array {
  return secp256k1.getPublicKey(secret, true);
}

export function keyHashOf(pubkey: Uint8Array): Uint8Array {
  return sha256d(pubkey).slice(0, KEYHASH_LEN);
}

function checksum(prefix: string, keyHash: Uint8Array): Uint8Array {
  return sha256d(concat(new TextEncoder().encode(prefix), keyHash)).slice(0, CHECKSUM_LEN);
}

export function addressFromPublicKey(pubkey: Uint8Array, prefix: string): string {
  const kh = keyHashOf(pubkey);
  return prefix + bytesToHex(concat(kh, checksum(prefix, kh)));
}

/** Returns the 20-byte key hash, or null if the address is malformed / has a bad checksum. */
export function decodeAddress(address: string, prefix: string): Uint8Array | null {
  if (!address.startsWith(prefix)) return null;
  const body = address.slice(prefix.length);
  if (body.length !== 2 * (KEYHASH_LEN + CHECKSUM_LEN) || !/^[0-9a-f]+$/.test(body)) return null;
  const raw = hexToBytes(body);
  const kh = raw.slice(0, KEYHASH_LEN);
  const sum = raw.slice(KEYHASH_LEN);
  const expected = checksum(prefix, kh);
  return sum.every((b, i) => b === expected[i]) ? kh : null;
}

export const isValidAddress = (address: string, prefix: string): boolean => decodeAddress(address, prefix) !== null;

export interface TransferInput {
  recipientKeyHash: Uint8Array;
  amount: bigint;
  fee: bigint;
  nonce: bigint;
  memo: Uint8Array;
}

function body(params: ChainParams, pubkey: Uint8Array, t: TransferInput): Uint8Array {
  return concat(
    uint(TX_VERSION, 1), uint(KIND_TRANSFER, 1), uint(params.chainId, 4),
    varBytes(pubkey), t.recipientKeyHash,
    uint(t.amount, 8), uint(t.fee, 8), uint(t.nonce, 8), varBytes(t.memo),
  );
}

export interface SignedTransfer { hex: string; txid: string; size: number }

/** Build and sign a transfer exactly like Wallet.sign_transfer (ECDSA secp256k1, RFC6979, low-S). */
export function signTransfer(secret: Uint8Array, params: ChainParams, t: TransferInput): SignedTransfer {
  if (t.amount <= 0n) throw new Error("amount must be positive");
  if (t.fee < params.minFee) throw new Error(`fee below network minimum (${params.minFee})`);
  if (t.memo.length > params.maxMemoBytes) throw new Error("memo too long");
  const pubkey = publicKeyOf(secret);
  const unsigned = body(params, pubkey, t);
  const digest = sha256d(concat(SIGNING_DOMAIN, unsigned));
  const sig = secp256k1.sign(digest, secret, { lowS: true }).toCompactRawBytes();
  const full = concat(unsigned, varBytes(sig));
  return { hex: bytesToHex(full), txid: bytesToHex(sha256d(full)), size: full.length };
}
