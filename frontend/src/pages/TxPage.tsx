import { Link, useParams } from "react-router-dom";
import { Badge, Card, CopyValue, ErrorState, KV, PageHeader, TableSkeleton } from "@/components/ui";
import { useTransaction } from "@/hooks/queries";
import { isHash } from "@/utils/format";

export function TxPage() {
  const txid = useParams().txid ?? "";
  const q = useTransaction(isHash(txid) ? txid : "");
  if (!isHash(txid)) return <ErrorState error={new Error("Invalid transaction id (expected 64 lowercase hex characters)")} />;
  if (q.isPending) return <TableSkeleton rows={8} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const t = q.data;
  return (
    <>
      <PageHeader title="Transaction" actions={t.confirmed ? <Badge tone="ok">Confirmed</Badge> : <Badge tone="warn">Pending in mempool</Badge>} />
      <Card><dl>
        <KV label="Txid"><CopyValue value={t.txid} full /></KV>
        <KV label="Type">{t.kind}</KV>
        <KV label="From">{t.sender ? <CopyValue value={t.sender} to={`/address/${t.sender}`} full /> : <span className="text-muted">Coinbase (block reward)</span>}</KV>
        <KV label="To"><CopyValue value={t.recipient} to={`/address/${t.recipient}`} full /></KV>
        <KV label="Amount"><span className="font-mono">{t.amount_formatted} BF</span></KV>
        <KV label="Fee"><span className="font-mono">{t.kind === "coinbase" ? "—" : `${t.fee_formatted} BF`}</span></KV>
        <KV label="Nonce">{t.nonce}</KV>
        <KV label="Size">{t.size} bytes</KV>
        <KV label="Block">{t.block_height !== null ? <Link className="text-brand hover:underline" to={`/blocks/height/${t.block_height}`}>#{t.block_height}</Link> : <span className="text-muted">Not yet mined</span>}{t.position !== null && ` · position ${t.position}`}</KV>
        <KV label="Memo (hex)">{t.memo_hex ? <span className="break-all font-mono text-xs">{t.memo_hex}</span> : <span className="text-muted">None</span>}</KV>
      </dl></Card>
    </>
  );
}
