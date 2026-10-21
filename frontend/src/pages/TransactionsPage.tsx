import { useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { api } from "@/api/endpoints";
import { Card, EmptyState, ErrorState, PageHeader, TableSkeleton } from "@/components/ui";
import { TxTable } from "@/features/transactions/TxTable";
import { useMempool, useStatus } from "@/hooks/queries";
import { config } from "@/config";
import type { Tx } from "@/types/api";

const RECENT_BLOCKS = 10;
type Tab = "pending" | "confirmed";

export function TransactionsPage() {
  const [tab, setTab] = useState<Tab>("pending");
  const [kind, setKind] = useState<"all" | "transfer" | "coinbase">("all");
  const [text, setText] = useState("");
  const status = useStatus();
  const mempool = useMempool(100);
  const top = status.data?.height ?? null;
  const heights = top === null ? [] : Array.from({ length: Math.min(RECENT_BLOCKS, top + 1) }, (_, i) => top - i);
  const blocks = useQueries({
    queries: heights.map((h) => ({ queryKey: ["block", "height", h], queryFn: ({ signal }: { signal: AbortSignal }) => api.blockByHeight(h, signal), enabled: tab === "confirmed", staleTime: Infinity })),
  });

  const source: Tx[] = tab === "pending" ? mempool.data?.transactions ?? [] : blocks.flatMap((b) => b.data?.transactions ?? []);
  const needle = text.trim().toLowerCase();
  const rows = source.filter((t) => (kind === "all" || t.kind === kind) && (!needle || [t.txid, t.sender ?? "", t.recipient].some((v) => v.toLowerCase().includes(needle))));
  const loading = tab === "pending" ? mempool.isPending : blocks.some((b) => b.isPending);
  const error = tab === "pending" ? mempool.error : blocks.find((b) => b.error)?.error;

  return (
    <>
      <PageHeader title="Transactions" subtitle={`The node has no global transaction index; confirmed transactions are read from the last ${RECENT_BLOCKS} blocks. Use search for older ones.`} />
      <Card>
        <div className="mb-4 flex flex-wrap items-end gap-3">
          <div role="tablist" aria-label="Transaction source" className="flex gap-1">
            {(["pending", "confirmed"] as const).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "btn-primary" : "btn-ghost"} onClick={() => setTab(t)}>{t === "pending" ? "Pending (mempool)" : "Recent confirmed"}</button>
            ))}
          </div>
          <div><label className="label" htmlFor="kind">Type</label><select id="kind" className="input" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}><option value="all">All</option><option value="transfer">Transfers</option><option value="coinbase">Coinbase</option></select></div>
          <div className="min-w-48 flex-1"><label className="label" htmlFor="filter">Filter by txid or address</label><input id="filter" className="input" value={text} maxLength={130} onChange={(e) => setText(e.target.value)} /></div>
        </div>
        {loading ? <TableSkeleton rows={6} /> : error ? <ErrorState error={error} /> : rows.length === 0
          ? <EmptyState title={tab === "pending" ? "No pending transactions" : "No matching transactions"} hint={tab === "pending" ? "The mempool is empty." : undefined} /> : <TxTable txs={rows} />}
        {tab === "pending" && mempool.data && mempool.data.count > mempool.data.transactions.length && <p className="mt-3 text-xs text-muted">Showing {mempool.data.transactions.length} of {mempool.data.count} pending (API limit 100).</p>}
        <p className="mt-3 text-xs text-muted">Refreshes every {config.pollIntervalMs / 1000}s.</p>
      </Card>
    </>
  );
}
