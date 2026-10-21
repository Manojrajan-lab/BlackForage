import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "@/api/endpoints";
import { Badge, Card, Dialog, ErrorState, KV, Notice, PageHeader, Spinner, TableSkeleton, Unavailable } from "@/components/ui";
import { AdminKeyNotice } from "@/features/settings/AdminKeyNotice";
import { useBlocks, useChainGuard, useMining, useStatus } from "@/hooks/queries";
import { useWallet } from "@/hooks/wallet";
import { describeError } from "@/utils/errors";
import { difficultyFromBits, workFromBits } from "@/utils/chain";
import { formatNumber, formatWork, timeAgo } from "@/utils/format";
import { isValidAddress } from "@/utils/txcodec";

export function MiningPage() {
  const qc = useQueryClient();
  const status = useStatus();
  const mining = useMining();
  const blocks = useBlocks(1);
  const wallet = useWallet();
  const { params } = useChainGuard();
  const [confirmStop, setConfirmStop] = useState(false);
  const tip = blocks.data?.[0];

  const schema = z.object({ address: z.string().trim().refine((v) => isValidAddress(v, params.addressPrefix), "Not a valid address (prefix, length or checksum)") });
  const f = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), values: { address: wallet.address ?? "" } });

  const start = useMutation({ mutationFn: (address: string) => api.startMining(address), onSuccess: () => qc.invalidateQueries() });
  const stop = useMutation({ mutationFn: () => api.stopMining(), onSuccess: async () => { setConfirmStop(false); await qc.invalidateQueries(); } });
  const running = mining.data?.mining ?? status.data?.mining ?? false;

  return (
    <>
      <PageHeader title="Mining" subtitle="Control the node's built-in Proof-of-Work miner" />
      <AdminKeyNotice />
      <Card title="Miner status">
        {mining.isPending ? <TableSkeleton rows={4} /> : mining.isError ? <ErrorState error={mining.error} onRetry={() => void mining.refetch()} /> : (
          <dl>
            <KV label="Miner">{running ? <Badge tone="ok">Running</Badge> : <Badge tone="warn">Stopped</Badge>}</KV>
            <KV label="Chain height">{status.data ? formatNumber(status.data.height) : "…"}</KV>
            <KV label="Current difficulty">{tip ? `${difficultyFromBits(tip.bits).toLocaleString("en-US", { maximumFractionDigits: 2 })}× pow limit (≈ ${formatWork(workFromBits(tip.bits))} per block)` : "…"}</KV>
            <KV label="Last block found">{tip ? `${timeAgo(tip.timestamp)} (#${tip.height})` : "…"}</KV>
          </dl>
        )}
        <p className="mt-3 text-xs text-muted">Status means the node's miner thread is active. It does not mean a block is guaranteed soon. Progress is observable only through new blocks.</p>
      </Card>

      <Card title="Start or stop mining">
        <form className="space-y-3" noValidate onSubmit={f.handleSubmit(({ address }) => start.mutate(address))}>
          <div><label className="label" htmlFor="miner">Reward address</label>
            <input id="miner" className="input font-mono" spellCheck={false} autoComplete="off" {...f.register("address")} />
            {f.formState.errors.address && <p role="alert" className="mt-1 text-xs text-bad">{f.formState.errors.address.message}</p>}
            {!wallet.address && <p className="mt-1 text-xs text-muted">Unlock a wallet to prefill its address.</p>}</div>
          {start.isError && <Notice tone="bad">{describeError(start.error)}</Notice>}
          {start.isSuccess && <Notice tone="ok">Start request accepted. The miner is now running for the given address; watch for new blocks.</Notice>}
          <div className="flex gap-2">
            <button className="btn-primary" disabled={start.isPending}>{start.isPending ? <><Spinner />Requesting…</> : "Start mining"}</button>
            <button type="button" className="btn-ghost" disabled={!running || stop.isPending} onClick={() => setConfirmStop(true)}>Stop mining</button>
          </div>
        </form>
      </Card>

      <Unavailable title="Not available from the node API" reason="The backend reports only whether mining is on. There is no hashrate, current block template, block reward or mining-configuration endpoint, so none are shown." backendChange="Add read-only fields (hashrate, template height, expected reward) to GET /v1/mining or /v1/status." />

      <Dialog open={confirmStop} onClose={() => setConfirmStop(false)} title="Stop mining?">
        <p className="text-sm text-muted">The node will stop producing blocks until mining is started again.</p>
        {stop.isError && <div className="mt-3"><Notice tone="bad">{describeError(stop.error)}</Notice></div>}
        <div className="mt-4 flex justify-end gap-2"><button className="btn-ghost" onClick={() => setConfirmStop(false)}>Cancel</button>
          <button className="btn-danger" disabled={stop.isPending} onClick={() => stop.mutate()}>{stop.isPending ? <Spinner /> : "Stop mining"}</button></div>
      </Dialog>
    </>
  );
}
