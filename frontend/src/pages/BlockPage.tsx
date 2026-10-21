import { Link, useParams } from "react-router-dom";
import { Card, CopyValue, EmptyState, ErrorState, KV, PageHeader, TableSkeleton } from "@/components/ui";
import { TxTable } from "@/features/transactions/TxTable";
import { useBlockByHash, useBlockByHeight } from "@/hooks/queries";
import { bitsToTarget, difficultyFromBits } from "@/utils/chain";
import { formatBytes, formatTimestamp, isHash, isHeight } from "@/utils/format";

export function BlockPage({ by }: { by: "height" | "hash" }) {
  const params = useParams();
  const raw = (by === "height" ? params.height : params.hash) ?? "";
  const valid = by === "height" ? isHeight(raw) : isHash(raw);
  const byHeight = useBlockByHeight(by === "height" && valid ? Number(raw) : null);
  const byHash = useBlockByHash(by === "hash" && valid ? raw : null);
  const q = by === "height" ? byHeight : byHash;

  if (!valid) return <ErrorState error={new Error(by === "height" ? "Invalid block height" : "Invalid block hash (expected 64 lowercase hex characters)")} />;
  if (q.isPending) return <TableSkeleton rows={8} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const b = q.data;

  return (
    <>
      <PageHeader title={`Block ${b.height}`} />
      <Card title="Details">
        <dl>
          <KV label="Hash"><CopyValue value={b.hash} full /></KV>
          <KV label="Previous hash">{b.height > 0 ? <CopyValue value={b.prev_hash} to={`/blocks/hash/${b.prev_hash}`} full /> : <span className="text-muted">Genesis</span>}</KV>
          <KV label="Merkle root"><CopyValue value={b.merkle_root} full /></KV>
          <KV label="Timestamp">{formatTimestamp(b.timestamp)}</KV>
          <KV label="Nonce"><span className="font-mono">{b.nonce}</span></KV>
          <KV label="Bits / difficulty"><span className="font-mono">0x{b.bits.toString(16)}</span> · {difficultyFromBits(b.bits).toLocaleString("en-US", { maximumFractionDigits: 2 })}× pow limit</KV>
          <KV label="Target"><span className="break-all font-mono text-xs">{bitsToTarget(b.bits).toString(16).padStart(64, "0")}</span></KV>
          <KV label="Version">{b.version}</KV>
          <KV label="Size">{formatBytes(b.size)}</KV>
        </dl>
        <div className="mt-4 flex gap-4 text-sm">
          {b.height > 0 && <Link className="text-brand hover:underline" to={`/blocks/height/${b.height - 1}`}>← Block {b.height - 1}</Link>}
          <Link className="text-brand hover:underline" to={`/blocks/height/${b.height + 1}`}>Block {b.height + 1} →</Link>
        </div>
      </Card>
      <Card title={`Transactions (${b.tx_count})`}>
        {b.transactions.length === 0 ? <EmptyState title="No transactions" /> : <TxTable txs={b.transactions} />}
      </Card>
    </>
  );
}
