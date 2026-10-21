import type { Tx } from "@/types/api";
import { Badge, CopyValue, Table } from "@/components/ui";

export function TxTable({ txs, perspective }: { txs: Tx[]; perspective?: string }) {
  return (
    <Table label="Transactions">
      <thead><tr className="border-b border-line">
        <th className="th">Txid</th><th className="th">Type</th><th className="th">From</th><th className="th">To</th>
        <th className="th text-right">Amount (BF)</th><th className="th text-right">Fee</th><th className="th">Status</th>
      </tr></thead>
      <tbody>
        {txs.map((t) => (
          <tr key={`${t.txid}-${t.position ?? "p"}`} className="border-b border-line/60 last:border-0">
            <td className="td"><CopyValue value={t.txid} to={`/tx/${t.txid}`} /></td>
            <td className="td"><Badge tone={t.kind === "coinbase" ? "warn" : "info"}>{t.kind}</Badge></td>
            <td className="td">{t.sender ? <CopyValue value={t.sender} to={`/address/${t.sender}`} head={6} tail={6} /> : <span className="text-muted">—</span>}</td>
            <td className="td"><CopyValue value={t.recipient} to={`/address/${t.recipient}`} head={6} tail={6} /></td>
            <td className="td whitespace-nowrap text-right font-mono">
              {perspective && t.sender === perspective && t.recipient !== perspective ? "−" : perspective && t.recipient === perspective ? "+" : ""}{t.amount_formatted}
            </td>
            <td className="td whitespace-nowrap text-right font-mono text-muted">{t.kind === "coinbase" ? "—" : t.fee_formatted}</td>
            <td className="td">{t.confirmed ? <Badge tone="ok">Block {t.block_height}</Badge> : <Badge tone="warn">Pending</Badge>}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
