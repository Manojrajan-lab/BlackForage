import { type ReactElement, useEffect } from "react";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { WalletProvider, useWallet } from "@/hooks/wallet";
import { CHAIN_PARAMS } from "@/utils/chain";
import { connection } from "@/api/client";
import { hexToBytes } from "@/utils/bytes";
import fixture from "./fixtures/python-backend.json";

export const ADDR = fixture.address;
export const OTHER = fixture.recipient;
export const H = "a".repeat(64);

export const status = (over = {}) => ({ network: "dev", chain_id: 1337, height: 7, tip: H, chainwork: "99", mempool_txs: 1, mempool_bytes: 200, total_supply: 0, total_supply_formatted: "350.00000000", mining: true, peers: 2, ...over });
export const tx = (over = {}) => ({ txid: "b".repeat(64), kind: "transfer", sender: ADDR, recipient: OTHER, amount: 100, amount_formatted: "0.00000100", fee: 1, fee_formatted: "0.00000001", nonce: 0, memo_hex: "", size: 150, block_height: 7, position: 1, confirmed: true, ...over });
export const block = (height: number, over = {}) => ({ hash: height.toString(16).padStart(64, "0"), height, version: 1, prev_hash: H, merkle_root: H, timestamp: 1_700_000_000 + height * 10, bits: 0x2000ffff, nonce: 5, tx_count: 1, size: 300, ...over });
export const account = (over = {}) => ({ address: ADDR, balance: 5_000_000_000, balance_formatted: "50.00000000", spendable: 5_000_000_000, spendable_formatted: "50.00000000", nonce: 0, next_nonce: 0, ...over });

type Handler = (url: URL, init?: RequestInit) => unknown | Response;
/** Route-based fetch stub; unknown routes fail the test loudly. */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: Array<{ path: string; init?: RequestInit }> = [];
  const fn = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = new URL(String(input));
    calls.push({ path: url.pathname + url.search, init });
    const key = Object.keys(routes).find((k) => url.pathname === k || url.pathname + url.search === k);
    if (!key) return Promise.reject(new Error(`unmocked ${url.pathname}${url.search}`));
    const out = routes[key]!(url, init);
    if (out instanceof Response) return Promise.resolve(out);
    return Promise.resolve(new Response(JSON.stringify(out), { status: 200, headers: { "Content-Type": "application/json" } }));
  });
  return { calls, fn };
}
export const errorResponse = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ error: { code, message } }), { status, headers: { "Content-Type": "application/json" } });

function Unlocker({ children }: { children: ReactElement }) {
  const w = useWallet();
  useEffect(() => { w.unlock(hexToBytes(fixture.secret_hex), CHAIN_PARAMS.dev); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return w.unlocked ? children : null;
}

export function renderApp(ui: ReactElement, opts: { route?: string; unlocked?: boolean; adminKey?: string } = {}) {
  connection.setBaseUrl("http://node.test");
  connection.setAdminKey(opts.adminKey ?? "");
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}><WalletProvider><MemoryRouter initialEntries={[opts.route ?? "/"]}>
      {opts.unlocked ? <Unlocker>{ui}</Unlocker> : ui}
    </MemoryRouter></WalletProvider></QueryClientProvider>,
  );
}
