// @vitest-environment node
import { describe, expect, it } from "vitest";
import fixture from "./fixtures/python-backend.json";
import { CHAIN_PARAMS } from "@/utils/chain";
import { hexToBytes, bytesToHex } from "@/utils/bytes";
import { addressFromPublicKey, decodeAddress, isValidAddress, publicKeyOf, signTransfer } from "@/utils/txcodec";
import { decryptKeystore, encryptKeystore, parseKeystore, KeystoreError } from "@/utils/keystore";

/** Fixtures were produced by the real Python backend (Wallet.sign_transfer / keystore.encrypt_key). */
const dev = CHAIN_PARAMS.dev;
const secret = hexToBytes(fixture.secret_hex);

describe("compatibility with the Python backend", () => {
  it("derives the same public key and address", () => {
    expect(bytesToHex(publicKeyOf(secret))).toBe(fixture.public_key);
    expect(addressFromPublicKey(publicKeyOf(secret), "BF")).toBe(fixture.address);
  });

  it("validates addresses with checksum", () => {
    expect(isValidAddress(fixture.address, "BF")).toBe(true);
    const flipped = fixture.address.slice(0, -1) + (fixture.address.endsWith("0") ? "1" : "0");
    expect(isValidAddress(flipped, "BF")).toBe(false);
    expect(isValidAddress("XX" + fixture.address.slice(2), "BF")).toBe(false);
    expect(decodeAddress(fixture.address.toUpperCase(), "BF")).toBeNull();
  });

  it("serialises and signs a transfer byte-for-byte like the backend", () => {
    const recipient = decodeAddress(fixture.recipient, "BF")!;
    const tx = signTransfer(secret, dev, {
      recipientKeyHash: recipient, amount: BigInt(fixture.amount), fee: BigInt(fixture.fee),
      nonce: BigInt(fixture.nonce), memo: hexToBytes(fixture.memo_hex),
    });
    expect(tx.hex).toBe(fixture.tx_hex);
    expect(tx.txid).toBe(fixture.txid);
  });

  it("enforces minimum fee and positive amount", () => {
    const base = { recipientKeyHash: new Uint8Array(20), nonce: 0n, memo: new Uint8Array() };
    expect(() => signTransfer(secret, CHAIN_PARAMS.mainnet, { ...base, amount: 1n, fee: 1n })).toThrow(/fee/);
    expect(() => signTransfer(secret, dev, { ...base, amount: 0n, fee: 1n })).toThrow(/amount/);
  });

  it("decrypts a keystore written by the Python backend", async () => {
    const file = parseKeystore(JSON.stringify(fixture.keystore));
    expect(bytesToHex(await decryptKeystore(file, fixture.password, "BF"))).toBe(fixture.secret_hex);
  });

  it("rejects a wrong password and tampered address", async () => {
    const file = parseKeystore(JSON.stringify(fixture.keystore));
    await expect(decryptKeystore(file, "wrong-password", "BF")).rejects.toBeInstanceOf(KeystoreError);
    await expect(decryptKeystore({ ...file, address: "BF" + "0".repeat(48) }, fixture.password, "BF")).rejects.toThrow();
  });

  it("round-trips its own keystore at the minimum scrypt cost", async () => {
    const file = await encryptKeystore(secret, "another-password", "BF", 2 ** 14);
    expect(file.address).toBe(fixture.address);
    expect(bytesToHex(await decryptKeystore(file, "another-password", "BF"))).toBe(fixture.secret_hex);
    await expect(encryptKeystore(secret, "short", "BF", 2 ** 14)).rejects.toThrow(/8 characters/);
  });

  it("rejects non-keystore input", () => {
    expect(() => parseKeystore("not json")).toThrow(KeystoreError);
    expect(() => parseKeystore("{}")).toThrow(KeystoreError);
  });
});
