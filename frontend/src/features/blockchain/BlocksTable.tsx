import type { BlockSummary } from "@/types/api";
import { CopyValue, Table } from "@/components/ui";
import { formatBytes, timeAgo } from "@/utils/format";
import { difficultyFromBits } from "@/utils/chain";

export function BlocksTable({ blocks }: { blocks: BlockSummary[] }) {
  return (
    <Table label="Blocks">
      <thead><tr className="border-b border-line">
        <th className="th">Height</th><th className="th">Hash</th><th className="th">Age</th>
        <th className="th text-right">Txs</th><th className="th text-right">Size</th><th className="th text-right">Difficulty</th>
      </tr></thead>
      <tbody>
        {blocks.map((b) => (
          <tr key={b.hash} className="border-b border-line/60 last:border-0">
            <td className="td font-mono"><CopyValue value={String(b.height)} to={`/blocks/height/${b.height}`} full /></td>
            <td className="td"><CopyValue value={b.hash} to={`/blocks/hash/${b.hash}`} /></td>
            <td className="td whitespace-nowrap text-muted">{timeAgo(b.timestamp)}</td>
            <td className="td text-right">{b.tx_count}</td>
            <td className="td whitespace-nowrap text-right">{formatBytes(b.size)}</td>
            <td className="td text-right">{difficultyFromBits(b.bits).toLocaleString("en-US", { maximumFractionDigits: 2 })}</td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
