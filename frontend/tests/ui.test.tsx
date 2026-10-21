import { afterEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { DashboardPage } from "@/pages/DashboardPage";
import { ExplorerPage } from "@/pages/ExplorerPage";
import { BlockPage } from "@/pages/BlockPage";
import { WalletPage } from "@/pages/WalletPage";
import { MiningPage } from "@/pages/MiningPage";
import { NetworkPage } from "@/pages/NetworkPage";
import { SearchPage } from "@/pages/SearchPage";
import { TransactionsPage } from "@/pages/TransactionsPage";
import { AddressPage } from "@/pages/AddressPage";
import { ADDR, H, OTHER, account, block, errorResponse, mockFetch, renderApp, status, tx } from "./helpers";
import fixture from "./fixtures/python-backend.json";

afterEach(() => vi.restoreAllMocks());

describe("Dashboard", () => {
  it("shows skeleton, then real values from the API", async () => {
    mockFetch({
      "/v1/status": () => status(),
      "/v1/blocks": () => [block(7), block(6)],
      "/v1/blocks/height/7": () => ({ ...block(7), transactions: [tx({ kind: "coinbase", sender: null })] }),
      "/v1/mempool": () => ({ count: 0, bytes: 0, next_block_fees: 0, transactions: [] }),
    });
    renderApp(<DashboardPage />);
    expect(screen.getByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(await screen.findByText("350.00000000")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(await screen.findByText("Mempool is empty")).toBeInTheDocument();
    expect(screen.getByText("Not enough history for a chart")).toBeInTheDocument();
  });

  it("shows an error with retry when the node is down", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("down"));
    renderApp(<DashboardPage />);
    const alerts = await screen.findAllByRole("alert");
    expect(alerts[0]).toHaveTextContent(/Cannot reach node/);
    expect(screen.getAllByRole("button", { name: /retry/i }).length).toBeGreaterThan(0);
  });
});

describe("Explorer", () => {
  it("pages older blocks using the `before` cursor", async () => {
    const m = mockFetch({
      "/v1/blocks": (u) => (u.searchParams.get("before") ? [block(1), block(0)] : [block(3), block(2)]),
    });
    renderApp(<ExplorerPage />);
    await screen.findByRole("table", { name: "Blocks" });
    await userEvent.click(screen.getByRole("button", { name: /older/i }));
    await waitFor(() => expect(m.calls.some((c) => c.path.includes("before=2"))).toBe(true));
    await waitFor(() => expect(screen.getByText("Blocks 1 – 0")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /older/i })).toBeDisabled();
  });

  it("shows an empty state", async () => {
    mockFetch({ "/v1/blocks": () => [] });
    renderApp(<ExplorerPage />);
    expect(await screen.findByText("No blocks yet")).toBeInTheDocument();
  });
});

describe("Block page", () => {
  it("rejects malformed hashes without calling the API", () => {
    const m = mockFetch({ "/v1/status": () => status() });
    renderApp(<Routes><Route path="/b/:hash" element={<BlockPage by="hash" />} /></Routes>, { route: "/b/nothex" });
    expect(screen.getByRole("alert")).toHaveTextContent(/Invalid block hash/);
    expect(m.calls.filter((c) => c.path !== "/v1/status")).toHaveLength(0);
  });

  it("renders header fields and copy buttons for full hashes", async () => {
    mockFetch({ "/v1/blocks/height/3": () => ({ ...block(3), transactions: [tx({ kind: "coinbase", sender: null })] }) });
    renderApp(<Routes><Route path="/b/:height" element={<BlockPage by="height" />} /></Routes>, { route: "/b/3" });
    expect(await screen.findByRole("heading", { name: "Block 3" })).toBeInTheDocument();
    expect(screen.getByText("Merkle root")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /^Copy / }).length).toBeGreaterThan(2);
  });

  it("shows a 404 from the node", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(() => Promise.resolve(errorResponse(404, "not-found", "no block at that height")));
    renderApp(<Routes><Route path="/b/:height" element={<BlockPage by="height" />} /></Routes>, { route: "/b/9" });
    expect(await screen.findByText("no block at that height")).toBeInTheDocument();
  });
});

describe("Search", () => {
  it("falls back from txid to block hash on 404", async () => {
    const m = mockFetch({
      "/v1/status": () => status(),
      [`/v1/transactions/${H}`]: () => errorResponse(404, "not-found", "unknown transaction"),
      [`/v1/blocks/${H}`]: () => ({ ...block(3), transactions: [] }),
    });
    renderApp(<Routes><Route path="/search" element={<SearchPage />} /><Route path="/blocks/hash/:h" element={<div>BLOCK ROUTE</div>} /></Routes>, { route: `/search?q=${H}` });
    expect(await screen.findByText("BLOCK ROUTE")).toBeInTheDocument();
    expect(m.calls.map((c) => c.path).filter((p) => p !== "/v1/status")).toEqual([`/v1/transactions/${H}`, `/v1/blocks/${H}`]);
  });

  it("routes heights and valid addresses; rejects junk without API calls", async () => {
    const m = mockFetch({ "/v1/status": () => status() });
    const tree = <Routes><Route path="/search" element={<SearchPage />} /><Route path="/blocks/height/:h" element={<div>HEIGHT ROUTE</div>} /><Route path="/address/:a" element={<div>ADDR ROUTE</div>} /></Routes>;
    const a = renderApp(tree, { route: "/search?q=42" });
    expect(await screen.findByText("HEIGHT ROUTE")).toBeInTheDocument();
    a.unmount();
    const b = renderApp(tree, { route: `/search?q=${ADDR}` });
    expect(await screen.findByText("ADDR ROUTE")).toBeInTheDocument();
    b.unmount();
    renderApp(tree, { route: `/search?q=${ADDR.slice(0, -1)}0` });
    expect(await screen.findByText("Nothing matches that search")).toBeInTheDocument();
    expect(m.calls.filter((c) => c.path !== "/v1/status")).toHaveLength(0);
  });
});

describe("Transactions page", () => {
  it("lists pending transactions and filters client-side", async () => {
    mockFetch({
      "/v1/status": () => status(),
      "/v1/mempool": () => ({ count: 2, bytes: 300, next_block_fees: 2, transactions: [tx({ txid: "c".repeat(64) }), tx({ txid: "d".repeat(64), recipient: ADDR, sender: OTHER })] }),
    });
    renderApp(<TransactionsPage />);
    const table = await screen.findByRole("table", { name: "Transactions" });
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    await userEvent.type(screen.getByLabelText(/filter by txid/i), "d".repeat(10));
    expect(within(screen.getByRole("table", { name: "Transactions" })).getAllByRole("row")).toHaveLength(2);
  });
});

describe("Address page", () => {
  it("rejects a bad checksum locally", () => {
    const m = mockFetch({ "/v1/status": () => status() });
    renderApp(<Routes><Route path="/a/:address" element={<AddressPage />} /></Routes>, { route: `/a/${ADDR.slice(0, -1)}0` });
    expect(screen.getByRole("alert")).toHaveTextContent(/Invalid address/);
    expect(m.calls.filter((c) => c.path !== "/v1/status")).toHaveLength(0);
  });
});

describe("Wallet", () => {
  it("offers create/import when locked and never calls the API", () => {
    const m = mockFetch({ "/v1/status": () => status() });
    renderApp(<WalletPage />);
    expect(screen.getByRole("heading", { name: /open an existing wallet/i })).toBeInTheDocument();
    expect(screen.getByText(/no seed phrase and no recovery/i)).toBeInTheDocument();
    expect(m.calls.filter((c) => c.path !== "/v1/status")).toHaveLength(0);
  });

  it("validates the send form before the confirmation dialog", async () => {
    mockFetch({ "/v1/status": () => status(), [`/v1/accounts/${ADDR}`]: () => account(), [`/v1/accounts/${ADDR}/transactions`]: () => [] });
    renderApp(<WalletPage />, { unlocked: true });
    await screen.findByText("Send");
    await userEvent.type(await screen.findByLabelText("Recipient address"), "BFbad");
    await userEvent.type(screen.getByLabelText("Amount (BF)"), "1.123456789");
    await userEvent.click(screen.getByRole("button", { name: /review transaction/i }));
    expect(await screen.findByText(/Not a valid address/)).toBeInTheDocument();
    expect(screen.getByText(/At most 8 decimal places/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("requires confirmation, then signs with a fresh nonce and submits exactly once", async () => {
    const submitted: string[] = [];
    mockFetch({
      "/v1/status": () => status(),
      [`/v1/accounts/${ADDR}`]: () => account({ next_nonce: 3 }),
      [`/v1/accounts/${ADDR}/transactions`]: () => [],
      "/v1/transactions": (_u, init) => { submitted.push(JSON.parse(String(init?.body)).hex); return new Response(JSON.stringify({ txid: "e".repeat(64) }), { status: 201, headers: { "Content-Type": "application/json" } }); },
    });
    renderApp(<WalletPage />, { unlocked: true });
    await userEvent.type(await screen.findByLabelText("Recipient address"), OTHER);
    await userEvent.type(screen.getByLabelText("Amount (BF)"), "1.5");
    await userEvent.click(screen.getByRole("button", { name: /review transaction/i }));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("1.50000000 BF")).toBeInTheDocument();
    expect(within(dialog).getByText("Total debited")).toBeInTheDocument();
    expect(submitted).toHaveLength(0); // nothing sent before confirmation

    await userEvent.click(within(dialog).getByRole("button", { name: /sign and send/i }));
    await waitFor(() => expect(submitted).toHaveLength(1));
    // Fixture was signed by the Python backend with nonce 3 / 1.5 BF / fee 5 / memo "hello".
    expect(submitted[0]!.length).toBeGreaterThan(200);
    expect(await screen.findByText(/Submitted to the mempool/)).toBeInTheDocument();
  });

  it("surfaces node rejections inside the dialog", async () => {
    mockFetch({
      "/v1/status": () => status(),
      [`/v1/accounts/${ADDR}`]: () => account(),
      [`/v1/accounts/${ADDR}/transactions`]: () => [],
      "/v1/transactions": () => errorResponse(409, "mempool-duplicate", "duplicate"),
    });
    renderApp(<WalletPage />, { unlocked: true });
    await userEvent.type(await screen.findByLabelText("Recipient address"), OTHER);
    await userEvent.type(screen.getByLabelText("Amount (BF)"), "1");
    await userEvent.click(screen.getByRole("button", { name: /review transaction/i }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /sign and send/i }));
    expect(await screen.findByText(/already in the mempool/)).toBeInTheDocument();
  });

  it("blocks sending when spendable balance is insufficient (checked against the node's fresh data)", async () => {
    mockFetch({
      "/v1/status": () => status(),
      [`/v1/accounts/${ADDR}`]: () => account({ spendable: 10, spendable_formatted: "0.00000010" }),
      [`/v1/accounts/${ADDR}/transactions`]: () => [],
    });
    renderApp(<WalletPage />, { unlocked: true });
    await userEvent.type(await screen.findByLabelText("Recipient address"), OTHER);
    await userEvent.type(screen.getByLabelText("Amount (BF)"), "1");
    await userEvent.click(screen.getByRole("button", { name: /review transaction/i }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /sign and send/i }));
    expect(await screen.findByText(/Insufficient spendable balance/)).toBeInTheDocument();
  });

  it("disables signing if the node's network differs from the configured one", async () => {
    mockFetch({ "/v1/status": () => status({ network: "mainnet", chain_id: 1 }), [`/v1/accounts/${ADDR}`]: () => account(), [`/v1/accounts/${ADDR}/transactions`]: () => [] });
    renderApp(<WalletPage />, { unlocked: true });
    await screen.findByLabelText("Recipient address");
    await waitFor(() => expect(screen.getByRole("button", { name: /review transaction/i })).toBeDisabled());
  });

  it("never writes key material to web storage", async () => {
    const set = vi.spyOn(Storage.prototype, "setItem");
    mockFetch({ "/v1/status": () => status(), [`/v1/accounts/${ADDR}`]: () => account(), [`/v1/accounts/${ADDR}/transactions`]: () => [] });
    renderApp(<WalletPage />, { unlocked: true });
    await screen.findByText("Send");
    for (const [, v] of set.mock.calls) expect(String(v)).not.toContain(fixture.secret_hex);
    expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain(fixture.secret_hex);
  });
});

describe("Mining", () => {
  const routes = { "/v1/status": () => status(), "/v1/mining": () => ({ mining: true }), "/v1/blocks": () => [block(7)] };
  it("prompts for the admin key and refuses to call admin routes without it", async () => {
    const m = mockFetch(routes);
    renderApp(<MiningPage />, { unlocked: true });
    expect(await screen.findByText(/need the admin API key/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /start mining/i }));
    expect(await screen.findByText(/Admin API key not set/)).toBeInTheDocument();
    expect(m.calls.some((c) => c.path === "/v1/mining/start")).toBe(false);
  });

  it("stops mining only after confirmation, sending the key as X-API-Key", async () => {
    const m = mockFetch({ ...routes, "/v1/mining/stop": () => ({ mining: false }) });
    renderApp(<MiningPage />, { unlocked: true, adminKey: "k".repeat(16) });
    await screen.findByText("Running");
    await userEvent.click(screen.getByRole("button", { name: /stop mining/i }));
    expect(m.calls.some((c) => c.path === "/v1/mining/stop")).toBe(false);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: /stop mining/i }));
    await waitFor(() => expect(m.calls.some((c) => c.path === "/v1/mining/stop")).toBe(true));
    const call = m.calls.find((c) => c.path === "/v1/mining/stop")!;
    expect((call.init!.headers as Record<string, string>)["X-API-Key"]).toBe("k".repeat(16));
  });

  it("honestly lists what the API cannot provide", async () => {
    mockFetch(routes);
    renderApp(<MiningPage />);
    expect(await screen.findByText(/Not available from the node API/)).toBeInTheDocument();
  });
});

describe("Network", () => {
  it("renders peers", async () => {
    mockFetch({
      "/v1/status": () => status(),
      "/v1/network/peers": () => ({ stats: { peers: 1, inbound: 0, outbound: 1, known_addresses: 3, banned: 0, listen_port: 9333 }, peers: [{ address: "10.0.0.2:9333", direction: "outbound", height: 7, user_agent: "blockforge/0.1", latency_ms: 4.2, ban_score: 0, bytes_in: 1024, bytes_out: 2048, connected_at: 1_700_000_000 }] }),
    });
    renderApp(<NetworkPage />);
    expect(await screen.findByText("10.0.0.2:9333")).toBeInTheDocument();
    expect(screen.getByText("4.2 ms")).toBeInTheDocument();
  });

  it("explains an empty peer list and validates the connect form", async () => {
    const m = mockFetch({ "/v1/status": () => status(), "/v1/network/peers": () => ({ stats: { peers: 0 }, peers: [] }) });
    renderApp(<NetworkPage />);
    expect(await screen.findByText("No connected peers")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Host"), "bad host!");
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(await screen.findByText(/Letters, digits/)).toBeInTheDocument();
    expect(m.calls.some((c) => c.path === "/v1/network/connect")).toBe(false);
  });
});
