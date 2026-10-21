import { useQuery } from "@tanstack/react-query";
import { Navigate, useSearchParams } from "react-router-dom";
import { api } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui";
import { useChainGuard } from "@/hooks/queries";
import { isHash, isHeight } from "@/utils/format";
import { isValidAddress } from "@/utils/txcodec";

/** Resolve a search string to a real page. A 64-hex value may be a txid or a block hash: ask the node. */
export function SearchPage() {
  const q = (useSearchParams()[0].get("q") ?? "").trim();
  const { params } = useChainGuard();
  const hash = isHash(q);
  const resolve = useQuery({
    queryKey: ["search", q],
    enabled: hash,
    retry: false,
    queryFn: async ({ signal }) => {
      try { await api.transaction(q, signal); return "tx" as const; }
      catch (e) { if (!(e instanceof ApiError) || e.status !== 404) throw e; }
      await api.blockByHash(q, signal);
      return "block" as const;
    },
  });

  if (!q) return <EmptyState title="Enter a search term" hint="Block height, block hash, transaction id or address." />;
  if (isHeight(q)) return <Navigate replace to={`/blocks/height/${q}`} />;
  if (isValidAddress(q, params.addressPrefix)) return <Navigate replace to={`/address/${q}`} />;
  if (!hash) return <EmptyState title="Nothing matches that search" hint="Addresses must be valid (prefix, length and checksum); hashes are 64 lowercase hex characters." />;
  if (resolve.isPending) return <TableSkeleton rows={3} />;
  if (resolve.isError) {
    return resolve.error instanceof ApiError && resolve.error.status === 404
      ? <EmptyState title="Not found" hint="No transaction or block with that hash is known to this node." />
      : <ErrorState error={resolve.error} onRetry={() => void resolve.refetch()} />;
  }
  return <Navigate replace to={resolve.data === "tx" ? `/tx/${q}` : `/blocks/hash/${q}`} />;
}
