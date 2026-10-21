import { useInfiniteQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "@/api/endpoints";
import { Card, CopyValue, EmptyState, ErrorState, KV, Notice, PageHeader, TableSkeleton } from "@/components/ui";
import { TxTable } from "@/features/transactions/TxTable";
import { useAccount, useChainGuard } from "@/hooks/queries";
import { isValidAddress } from "@/utils/txcodec";
import type { Tx } from "@/types/api";

const LIMIT = 25;

export function AddressPage() {
  const address = useParams().address ?? "";
  const { params } = useChainGuard();
  const valid = isValidAddress(address, params.addressPrefix);
  const account = useAccount(valid ? address : null);
  const history = useInfiniteQuery({
    queryKey: ["address-history", address],
    enabled: valid,
    initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam, signal }) => api.accountTransactions(address, { limit: LIMIT, before: pageParam }, signal),
    // `before` is "blocks below this height" (exclusive). Using lastHeight + 1 keeps same-block
    // transactions that a limit cut off; duplicates are removed below.
    getNextPageParam: (last: Tx[]) => (last.length < LIMIT ? undefined : (last[last.length - 1]!.block_height ?? 0) + 1),
  });

  if (!valid) return <ErrorState error={new Error("Invalid address (wrong prefix, length or checksum)")} />;
  const seen = new Set<string>();
  const txs = (history.data?.pages.flat() ?? []).filter((t) => (seen.has(t.txid) ? false : (seen.add(t.txid), true)));
  const noProgress = history.data && history.data.pages.length > 1 && history.data.pages[history.data.pages.length - 1]!.every((t) => !txs.includes(t));

  return (
    <>
      <PageHeader title="Address" subtitle={address} />
      <Card title="Account">
        {account.isPending ? <TableSkeleton rows={4} /> : account.isError ? <ErrorState error={account.error} onRetry={() => void account.refetch()} /> : (
          <dl>
            <KV label="Address"><CopyValue value={account.data.address} full /></KV>
            <KV label="Balance"><span className="font-mono">{account.data.balance_formatted} BF</span></KV>
            <KV label="Spendable"><span className="font-mono">{account.data.spendable_formatted} BF</span> <span className="text-xs text-muted">(excludes immature coinbase rewards and pending spends)</span></KV>
            <KV label="Confirmed nonce">{account.data.nonce}</KV>
            <KV label="Next nonce">{account.data.next_nonce}</KV>
          </dl>
        )}
      </Card>
      <Card title="Confirmed transactions">
        <Notice tone="info">Only confirmed transactions are indexed by the node; pending ones appear under Transactions → Pending.</Notice>
        <div className="mt-3">
          {history.isPending ? <TableSkeleton /> : history.isError ? <ErrorState error={history.error} onRetry={() => void history.refetch()} /> : txs.length === 0
            ? <EmptyState title="No confirmed transactions" /> : <TxTable txs={txs} perspective={address} />}
        </div>
        {history.hasNextPage && !noProgress && <div className="mt-4 text-center"><button className="btn-ghost" disabled={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>{history.isFetchingNextPage ? "Loading…" : "Load more"}</button></div>}
      </Card>
    </>
  );
}
