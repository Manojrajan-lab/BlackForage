import { z } from "zod";

/** Response schemas mirror blockforge/api/schemas.py and routes.py exactly. */
export const statusSchema = z.object({
  network: z.string(),
  chain_id: z.number().int(),
  height: z.number().int().nonnegative(),
  tip: z.string(),
  chainwork: z.string(),
  mempool_txs: z.number().int(),
  mempool_bytes: z.number().int(),
  total_supply: z.number().int(),
  total_supply_formatted: z.string(),
  mining: z.boolean(),
  peers: z.number().int(),
});
export type NodeStatus = z.infer<typeof statusSchema>;

export const txSchema = z.object({
  txid: z.string(),
  kind: z.enum(["coinbase", "transfer"]),
  sender: z.string().nullable(),
  recipient: z.string(),
  amount: z.number().int(),
  amount_formatted: z.string(),
  fee: z.number().int(),
  fee_formatted: z.string(),
  nonce: z.number().int(),
  memo_hex: z.string(),
  size: z.number().int(),
  block_height: z.number().int().nullable(),
  position: z.number().int().nullable(),
  confirmed: z.boolean(),
});
export type Tx = z.infer<typeof txSchema>;

const blockBase = {
  hash: z.string(),
  height: z.number().int(),
  version: z.number().int(),
  prev_hash: z.string(),
  merkle_root: z.string(),
  timestamp: z.number().int(),
  bits: z.number().int(),
  nonce: z.number().int(),
  tx_count: z.number().int(),
  size: z.number().int(),
};
export const blockSummarySchema = z.object(blockBase);
export type BlockSummary = z.infer<typeof blockSummarySchema>;
export const blockSchema = z.object({ ...blockBase, transactions: z.array(txSchema) });
export type Block = z.infer<typeof blockSchema>;

export const accountSchema = z.object({
  address: z.string(),
  balance: z.number().int(),
  balance_formatted: z.string(),
  spendable: z.number().int(),
  spendable_formatted: z.string(),
  nonce: z.number().int(),
  next_nonce: z.number().int(),
});
export type Account = z.infer<typeof accountSchema>;

export const mempoolSchema = z.object({
  count: z.number().int(),
  bytes: z.number().int(),
  next_block_fees: z.number().int(),
  transactions: z.array(txSchema),
});
export type Mempool = z.infer<typeof mempoolSchema>;

export const peerSchema = z.object({
  address: z.string(),
  direction: z.enum(["inbound", "outbound"]),
  height: z.number().int().nullable(),
  user_agent: z.string().nullable(),
  latency_ms: z.number().nullable(),
  ban_score: z.number(),
  bytes_in: z.number(),
  bytes_out: z.number(),
  connected_at: z.number(),
});
export type Peer = z.infer<typeof peerSchema>;

export const peersSchema = z.object({
  stats: z.object({
    peers: z.number().int(),
    inbound: z.number().int().optional(),
    outbound: z.number().int().optional(),
    known_addresses: z.number().int().optional(),
    banned: z.number().int().optional(),
    listen_port: z.number().int().optional(),
  }),
  peers: z.array(peerSchema),
});
export type PeersResponse = z.infer<typeof peersSchema>;

export const healthSchema = z.object({ status: z.string(), height: z.number().int() });
export const miningSchema = z.object({ mining: z.boolean() });
export const submitTxSchema = z.object({ txid: z.string() });
export const miningStartSchema = z.object({ mining: z.boolean(), address: z.string() });
export const connectSchema = z.object({ status: z.string() });
