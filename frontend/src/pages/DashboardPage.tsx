import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, CopyValue, EmptyState, ErrorState, PageHeader, Stat, TableSkeleton } from "@/components/ui";
import { BlocksTable } from "@/features/blockchain/BlocksTable";
import { TxTable } from "@/features/transactions/TxTable";
import { useAccount, useBlockByHeight, useBlocks, useMempool, useStatus } from "@/hooks/queries";
import { useWallet } from "@/hooks/wallet";
import { difficultyFromBits, workFromBits } from "@/utils/chain";
import { formatNumber, formatWork, timeAgo } from "@/utils/format";

export function DashboardPage() {
  const status = useStatus();
  const blocks = useBlocks(10);
  const latest = useBlockByHeight(status.data?.height ?? null);
  const mempool = useMempool(5);
  const wallet = useWallet();
  const account = useAccount(wallet.address);
  const tip = blocks.data?.[0];

  // Real inter-block times from the blocks we actually fetched; only drawn with enough history.
  const intervals = (blocks.data ?? []).slice(0, -1).map((b, i) => ({ height: b.height, seconds: b.timestamp - blocks.data![i + 1]!.timestamp })).reverse();

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Live data from your BlockForge node" />
      {status.isError && <ErrorState error={status.error} onRetry={() => void status.refetch()} />}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Block height" loading={status.isPending} value={status.data && formatNumber(status.data.height)} hint={tip && `Latest block ${timeAgo(tip.timestamp)}`} />
        <Stat label="Mining" loading={status.isPending} value={status.data && (status.data.mining ? <Badge tone="ok">Active</Badge> : <Badge tone="warn">Idle</Badge>)} hint="This node's miner" />
        <Stat label="Peers" loading={status.isPending} value={status.data && status.data.peers} hint="Connected P2P peers" />
        <Stat label="Mempool" loading={status.isPending} value={status.data && `${status.data.mempool_txs} tx`} hint={status.data && `${formatNumber(status.data.mempool_bytes)} bytes`} />
        <Stat label="Difficulty (vs. pow limit)" loading={blocks.isPending} value={tip && difficultyFromBits(tip.bits).toLocaleString("en-US", { maximumFractionDigits: 2 })} hint={tip && `≈ ${formatWork(workFromBits(tip.bits))} per block`} />
        <Stat label="Total supply (BF)" loading={status.isPending} value={status.data?.total_supply_formatted} />
        <Stat label="Network" loading={status.isPending} value={status.data && status.data.network} hint={status.data && `chain id ${status.data.chain_id}`} />
        <Stat label="Chainwork" loading={status.isPending} value={status.data && <span className="font-mono text-sm">{status.data.chainwork}</span>} />
      </div>

      {wallet.address && (
        <Card title="Your wallet" action={<Link to="/wallet" className="text-xs text-brand hover:underline">Open wallet</Link>}>
          {account.isPending ? <TableSkeleton rows={1} /> : account.isError ? <ErrorState error={account.error} /> : (
            <div className="flex flex-wrap gap-6 text-sm"><div><div className="text-xs text-muted">Balance</div><div className="font-mono text-lg">{account.data.balance_formatted} BF</div></div>
              <div><div className="text-xs text-muted">Spendable</div><div className="font-mono text-lg">{account.data.spendable_formatted} BF</div></div>
              <div className="min-w-0"><div className="text-xs text-muted">Address</div><CopyValue value={wallet.address} to={`/address/${wallet.address}`} /></div></div>
          )}
        </Card>
      )}

      <Card title="Recent blocks" action={<Link to="/explorer" className="text-xs text-brand hover:underline">View all</Link>}>
        {blocks.isPending ? <TableSkeleton /> : blocks.isError ? <ErrorState error={blocks.error} onRetry={() => void blocks.refetch()} /> : <BlocksTable blocks={blocks.data.slice(0, 8)} />}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Pending transactions">
          {mempool.isPending ? <TableSkeleton rows={3} /> : mempool.isError ? <ErrorState error={mempool.error} /> : mempool.data.transactions.length === 0
            ? <EmptyState title="Mempool is empty" hint="Submitted transactions appear here until they are mined." /> : <TxTable txs={mempool.data.transactions} />}
        </Card>
        <Card title={tip ? `Transactions in block ${tip.height}` : "Latest block transactions"}>
          {latest.isPending ? <TableSkeleton rows={3} /> : latest.isError ? <ErrorState error={latest.error} /> : <TxTable txs={latest.data.transactions.slice(0, 5)} />}
        </Card>
      </div>

      <Card title="Seconds between recent blocks">
        {intervals.length < 5 ? <EmptyState title="Not enough history for a chart" hint="A chart appears once at least 6 blocks exist." /> : (
          <div className="h-56" role="img" aria-label="Bar chart of seconds between recent blocks">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={intervals}><CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" /><XAxis dataKey="height" stroke="rgb(var(--muted))" fontSize={11} /><YAxis stroke="rgb(var(--muted))" fontSize={11} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "rgb(var(--card))", border: "1px solid rgb(var(--line))" }} /><Bar dataKey="seconds" fill="rgb(var(--brand))" /></BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </Card>
    </>
  );
}
