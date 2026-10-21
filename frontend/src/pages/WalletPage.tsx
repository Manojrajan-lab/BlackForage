import { Lock } from "lucide-react";
import { Card, CopyValue, EmptyState, ErrorState, KV, Notice, PageHeader, TableSkeleton } from "@/components/ui";
import { CreateOrImport } from "@/features/wallet/CreateOrImport";
import { SendForm } from "@/features/wallet/SendForm";
import { TxTable } from "@/features/transactions/TxTable";
import { useAccount, useAccountTxs } from "@/hooks/queries";
import { useWallet } from "@/hooks/wallet";

export function WalletPage() {
  const wallet = useWallet();
  const account = useAccount(wallet.address);
  const history = useAccountTxs(wallet.address, 25);

  if (!wallet.unlocked) {
    return (
      <>
        <PageHeader title="Wallet" subtitle="Keys are decrypted and used only in this browser tab's memory." />
        <CreateOrImport />
        <Notice tone="info">Custody note: this is a software wallet. Your key exists in page memory while unlocked, so a compromised browser or malicious extension could use it. It is not hardware-backed. Locking, reloading or closing the tab discards it.</Notice>
      </>
    );
  }

  return (
    <>
      <PageHeader title="Wallet" actions={<button className="btn-ghost" onClick={wallet.lock}><Lock className="h-4 w-4" />Lock wallet</button>} />
      <Card title="Account">
        {account.isPending ? <TableSkeleton rows={4} /> : account.isError ? <ErrorState error={account.error} onRetry={() => void account.refetch()} /> : (
          <dl>
            <KV label="Address"><CopyValue value={account.data.address} to={`/address/${account.data.address}`} full /></KV>
            <KV label="Balance"><span className="font-mono text-lg">{account.data.balance_formatted} BF</span></KV>
            <KV label="Spendable"><span className="font-mono">{account.data.spendable_formatted} BF</span></KV>
            <KV label="Next nonce">{account.data.next_nonce}</KV>
          </dl>
        )}
      </Card>
      {account.data && <Card title="Send"><SendForm account={account.data} /></Card>}
      <Card title="Transaction history">
        {history.isPending ? <TableSkeleton /> : history.isError ? <ErrorState error={history.error} onRetry={() => void history.refetch()} /> : history.data.length === 0
          ? <EmptyState title="No confirmed transactions yet" hint="Mined rewards and received transfers appear here once confirmed." /> : <TxTable txs={history.data} perspective={wallet.address ?? undefined} />}
      </Card>
    </>
  );
}
