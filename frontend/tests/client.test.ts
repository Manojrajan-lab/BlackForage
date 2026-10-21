import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/api/endpoints";
import { ApiError, connection } from "@/api/client";

const okStatus = {
  network: "dev", chain_id: 1337, height: 5, tip: "a".repeat(64), chainwork: "123", mempool_txs: 0,
  mempool_bytes: 0, total_supply: 0, total_supply_formatted: "0.00000000", mining: false, peers: 0,
};
const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));

beforeEach(() => { connection.setBaseUrl("http://node.test"); connection.setAdminKey(""); });
afterEach(() => vi.restoreAllMocks());

describe("api client", () => {
  it("parses a valid response", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply(okStatus));
    expect((await api.status()).height).toBe(5);
    expect(f.mock.calls[0]![0]).toBe("http://node.test/v1/status");
  });

  it("maps the backend error envelope", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ error: { code: "not-found", message: "unknown block" } }, 404));
    await expect(api.blockByHeight(99)).rejects.toMatchObject({ kind: "http", status: 404, code: "not-found", message: "unknown block" });
  });

  it("flags malformed responses", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ height: "nope" }));
    await expect(api.status()).rejects.toMatchObject({ kind: "malformed" });
  });

  it("reports unreachable nodes and does not retry 4xx", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("fetch failed"));
    const err = (await api.status().then(() => null, (e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.kind).toBe("network");
    expect(err.retryable).toBe(true);
    expect(new ApiError("x", "http", 404).retryable).toBe(false);
  });

  it("never sends admin calls without a key, and sends X-API-Key when set", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply({ mining: true, address: "BFx" }));
    await expect(api.startMining("BFx")).rejects.toMatchObject({ code: "no-admin-key" });
    expect(f).not.toHaveBeenCalled();
    connection.setAdminKey("k".repeat(16));
    await api.startMining("BFx");
    expect((f.mock.calls[0]![1]!.headers as Record<string, string>)["X-API-Key"]).toBe("k".repeat(16));
  });

  it("builds paging query strings", async () => {
    const f = vi.spyOn(globalThis, "fetch").mockImplementation(() => reply([]));
    await api.blocks({ limit: 10, before: 50 });
    expect(f.mock.calls[0]![0]).toBe("http://node.test/v1/blocks?limit=10&before=50");
  });
});
