import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { config } from "@/config";
import { CHAIN_PARAMS, type ChainParams } from "@/utils/chain";

const poll = config.pollIntervalMs;

export const retryPolicy = (failures: number, err: unknown): boolean =>
  failures < 2 && (!(err instanceof ApiError) || err.retryable);

export const useStatus = () => useQuery({ queryKey: ["status"], queryFn: ({ signal }) => api.status(signal), refetchInterval: poll });
export const useMempool = (limit = 50) => useQuery({ queryKey: ["mempool", limit], queryFn: ({ signal }) => api.mempool(limit, signal), refetchInterval: poll });
export const usePeers = () => useQuery({ queryKey: ["peers"], queryFn: ({ signal }) => api.peers(signal), refetchInterval: poll });
export const useMining = () => useQuery({ queryKey: ["mining"], queryFn: ({ signal }) => api.mining(signal), refetchInterval: poll });

export const useBlocks = (limit: number, before?: number) =>
  useQuery({ queryKey: ["blocks", limit, before ?? "tip"], queryFn: ({ signal }) => api.blocks({ limit, before }, signal), placeholderData: keepPreviousData, refetchInterval: before === undefined ? poll : false });

export const useBlockByHeight = (height: number | null) =>
  useQuery({ queryKey: ["block", "height", height], queryFn: ({ signal }) => api.blockByHeight(height!, signal), enabled: height !== null });
export const useBlockByHash = (hash: string | null) =>
  useQuery({ queryKey: ["block", "hash", hash], queryFn: ({ signal }) => api.blockByHash(hash!, signal), enabled: hash !== null });

export const useTransaction = (txid: string) =>
  useQuery({ queryKey: ["tx", txid], queryFn: ({ signal }) => api.transaction(txid, signal), refetchInterval: (q) => (q.state.data?.confirmed ? false : poll) });

export const useAccount = (address: string | null) =>
  useQuery({ queryKey: ["account", address], queryFn: ({ signal }) => api.account(address!, signal), enabled: address !== null, refetchInterval: poll });

export const useAccountTxs = (address: string | null, limit: number, before?: number) =>
  useQuery({ queryKey: ["account-txs", address, limit, before ?? "tip"], queryFn: ({ signal }) => api.accountTransactions(address!, { limit, before }, signal), enabled: address !== null, placeholderData: keepPreviousData });

/** Chain params for signing, plus whether the node agrees with the configured network. */
export function useChainGuard(): { params: ChainParams; mismatch: string | null; ready: boolean } {
  const { data } = useStatus();
  const params = CHAIN_PARAMS[config.network];
  if (!data) return { params, mismatch: null, ready: false };
  const mismatch = data.network !== params.network || data.chain_id !== params.chainId
    ? `Node reports network "${data.network}" (chain ${data.chain_id}) but this frontend is configured for "${params.network}" (chain ${params.chainId}). Signing is disabled.`
    : null;
  return { params, mismatch, ready: true };
}

export function useRefreshChain() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}
