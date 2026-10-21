import { z } from "zod";
import { request } from "./client";
import {
  accountSchema, blockSchema, blockSummarySchema, connectSchema, healthSchema, mempoolSchema,
  miningSchema, miningStartSchema, peersSchema, statusSchema, submitTxSchema, txSchema,
} from "@/types/api";

const enc = encodeURIComponent;

function page(params: { limit?: number; before?: number }): string {
  const q = new URLSearchParams();
  if (params.limit !== undefined) q.set("limit", String(params.limit));
  if (params.before !== undefined) q.set("before", String(params.before));
  const qs = q.toString();
  return qs ? `?${qs}` : "";
}

/** One function per real backend route (blockforge/api/routes.py). */
export const api = {
  health: (signal?: AbortSignal) => request("/health", { schema: healthSchema, signal }),
  status: (signal?: AbortSignal) => request("/v1/status", { schema: statusSchema, signal }),
  blocks: (params: { limit?: number; before?: number } = {}, signal?: AbortSignal) =>
    request(`/v1/blocks${page(params)}`, { schema: z.array(blockSummarySchema), signal }),
  blockByHeight: (height: number, signal?: AbortSignal) =>
    request(`/v1/blocks/height/${height}`, { schema: blockSchema, signal }),
  blockByHash: (hash: string, signal?: AbortSignal) =>
    request(`/v1/blocks/${enc(hash)}`, { schema: blockSchema, signal }),
  transaction: (txid: string, signal?: AbortSignal) =>
    request(`/v1/transactions/${enc(txid)}`, { schema: txSchema, signal }),
  submitTransaction: (hex: string) =>
    request("/v1/transactions", { method: "POST", body: { hex }, schema: submitTxSchema }),
  mempool: (limit = 50, signal?: AbortSignal) =>
    request(`/v1/mempool?limit=${limit}`, { schema: mempoolSchema, signal }),
  account: (address: string, signal?: AbortSignal) =>
    request(`/v1/accounts/${enc(address)}`, { schema: accountSchema, signal }),
  accountTransactions: (address: string, params: { limit?: number; before?: number } = {}, signal?: AbortSignal) =>
    request(`/v1/accounts/${enc(address)}/transactions${page(params)}`, { schema: z.array(txSchema), signal }),
  peers: (signal?: AbortSignal) => request("/v1/network/peers", { schema: peersSchema, signal }),
  mining: (signal?: AbortSignal) => request("/v1/mining", { schema: miningSchema, signal }),
  // Admin endpoints need X-API-Key; the backend answers 403 when BLOCKFORGE_API_KEY is unset.
  startMining: (address: string) =>
    request("/v1/mining/start", { method: "POST", body: { address }, schema: miningStartSchema, admin: true }),
  stopMining: () => request("/v1/mining/stop", { method: "POST", body: {}, schema: miningSchema, admin: true }),
  connectPeer: (host: string, port: number) =>
    request("/v1/network/connect", { method: "POST", body: { host, port }, schema: connectSchema, admin: true }),
};
