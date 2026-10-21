// @vitest-environment node
/**
 * Opt-in integration test against a REAL running node. Skipped unless BLOCKFORGE_LIVE_URL is set.
 * The node must run the dev network with mining enabled and BLOCKFORGE_MINER_ADDRESS set to the
 * address in tests/fixtures/python-backend.json (a throwaway test key), plus BLOCKFORGE_API_KEY.
 */
import { describe, expect, it } from "vitest";
import fixture from "../fixtures/python-backend.json";
import { api } from "@/api/endpoints";
import { ApiError, connection } from "@/api/client";
import { CHAIN_PARAMS } from "@/utils/chain";
import { bytesToHex, hexToBytes } from "@/utils/bytes";
import { decodeAddress, signTransfer, publicKeyOf, addressFromPublicKey } from "@/utils/txcodec";

const url = process.env.BLOCKFORGE_LIVE_URL;
const adminKey = process.env.BLOCKFORGE_LIVE_ADMIN_KEY ?? "";
const origin = process.env.BLOCKFORGE_LIVE_ORIGIN ?? "http://localhost:5173";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe.skipIf(!url)("live backend", () => {
  connection.setBaseUrl(url ?? "http://127.0.0.1:8000");
  const secret = hexToBytes(fixture.secret_hex);
  const me = addressFromPublicKey(publicKeyOf(secret), "BF");

  it("every read endpoint matches our response schemas", async () => {
    const st = await api.status();
    expect(st.network).toBe("dev");
    expect(st.chain_id).toBe(CHAIN_PARAMS.dev.chainId);
    expect((await api.health()).status).toBe("ok");
    const blocks = await api.blocks({ limit: 5 });
    expect(blocks.length).toBe(5);
    const full = await api.blockByHeight(blocks[0]!.height);
    expect(full.transactions[0]!.kind).toBe("coinbase");
    expect((await api.blockByHash(full.hash)).hash).toBe(full.hash);
    expect((await api.transaction(full.transactions[0]!.txid)).confirmed).toBe(true);
    await api.mempool(10);
    await api.peers();
    await api.mining();
    const acct = await api.account(me);
    expect(BigInt(acct.balance)).toBeGreaterThan(0n);
    expect((await api.accountTransactions(me, { limit: 5 })).length).toBeGreaterThan(0);
  });

  it("returns the documented error envelope", async () => {
    const e = (await api.blockByHeight(99_999_999).then(() => null, (x: unknown) => x)) as ApiError;
    expect(e).toMatchObject({ kind: "http", status: 404, code: "not-found" });
    const bad = (await api.account("BFnotanaddress").then(() => null, (x: unknown) => x)) as ApiError;
    expect(bad).toMatchObject({ status: 400, code: "bad-address" });
  });

  it("signs in the browser code path and the node accepts, mines and indexes the transfer", async () => {
    const recipient = CHAIN_PARAMS.dev.addressPrefix + bytesToHex(new Uint8Array(24).fill(7)); // checksum is wrong on purpose
    expect(decodeAddress(recipient, "BF")).toBeNull();
    const to = fixture.recipient;
    const before = await api.account(to);
    const acct = await api.account(me);
    const tx = signTransfer(secret, CHAIN_PARAMS.dev, {
      recipientKeyHash: decodeAddress(to, "BF")!, amount: 123_456n, fee: 10n, nonce: BigInt(acct.next_nonce), memo: new TextEncoder().encode("live-test"),
    });
    const res = await api.submitTransaction(tx.hex);
    expect(res.txid).toBe(tx.txid);
    const dup = (await api.submitTransaction(tx.hex).then(() => null, (x: unknown) => x)) as ApiError;
    expect(dup).toMatchObject({ status: 409 });

    let confirmed = false;
    for (let i = 0; i < 40 && !confirmed; i++) { await sleep(500); confirmed = (await api.transaction(tx.txid)).confirmed; }
    expect(confirmed).toBe(true);
    const after = await api.account(to);
    expect(BigInt(after.balance) - BigInt(before.balance)).toBe(123_456n);
    expect((await api.accountTransactions(to, { limit: 10 })).some((t) => t.txid === tx.txid)).toBe(true);
  }, 30_000);

  it("rejects a transaction signed for another chain", async () => {
    const acct = await api.account(me);
    const wrong = signTransfer(secret, { ...CHAIN_PARAMS.dev, chainId: 9999 }, {
      recipientKeyHash: decodeAddress(fixture.recipient, "BF")!, amount: 1n, fee: 10n, nonce: BigInt(acct.next_nonce), memo: new Uint8Array(),
    });
    const e = (await api.submitTransaction(wrong.hex).then(() => null, (x: unknown) => x)) as ApiError;
    expect(e).toMatchObject({ status: 400 });
  });

  it("allows the configured CORS origin", async () => {
    const r = await fetch(`${url}/v1/status`, { headers: { Origin: origin } });
    expect(r.headers.get("access-control-allow-origin")).toBe(origin);
  });

  it.skipIf(!adminKey)("admin endpoints: key required, wrong key rejected, stop/start work", async () => {
    connection.setAdminKey("");
    await expect(api.stopMining()).rejects.toMatchObject({ code: "no-admin-key" });
    connection.setAdminKey("x".repeat(20));
    await expect(api.stopMining()).rejects.toMatchObject({ status: 401, code: "unauthorized" });
    connection.setAdminKey(adminKey);
    expect((await api.stopMining()).mining).toBe(false);
    expect((await api.mining()).mining).toBe(false);
    expect((await api.startMining(me)).mining).toBe(true);
    expect((await api.mining()).mining).toBe(true);
    await expect(api.startMining("BFbad")).rejects.toMatchObject({ status: 400, code: "bad-address" });
    const peer = await api.connectPeer("127.0.0.1", 9).then((r) => r, (e: unknown) => e);
    expect(peer).toBeDefined();
  });
});
