import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { api } from "@/api/endpoints";
import { Badge, Card, EmptyState, ErrorState, Notice, PageHeader, Spinner, Stat, Table, TableSkeleton } from "@/components/ui";
import { AdminKeyNotice } from "@/features/settings/AdminKeyNotice";
import { usePeers, useStatus } from "@/hooks/queries";
import { describeError } from "@/utils/errors";
import { formatBytes, timeAgo } from "@/utils/format";

const schema = z.object({
  host: z.string().trim().min(1, "Host is required").max(253).regex(/^[A-Za-z0-9._:-]+$/, "Letters, digits, dots, dashes and colons only"),
  port: z.coerce.number({ invalid_type_error: "Port must be a number" }).int().min(1).max(65535),
});

export function NetworkPage() {
  const qc = useQueryClient();
  const status = useStatus();
  const peers = usePeers();
  const f = useForm<z.input<typeof schema>, unknown, z.output<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { host: "", port: 9333 } });
  const connect = useMutation({ mutationFn: (v: z.output<typeof schema>) => api.connectPeer(v.host, v.port), onSuccess: async () => { f.reset(); await qc.invalidateQueries({ queryKey: ["peers"] }); } });
  const s = peers.data?.stats;

  return (
    <>
      <PageHeader title="Network" subtitle="Peer-to-peer connections of this node" />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Connected peers" loading={peers.isPending} value={s?.peers} />
        <Stat label="Inbound / outbound" loading={peers.isPending} value={s && `${s.inbound ?? 0} / ${s.outbound ?? 0}`} />
        <Stat label="Known addresses" loading={peers.isPending} value={s?.known_addresses ?? "—"} />
        <Stat label="P2P listen port" loading={peers.isPending} value={s?.listen_port ?? "—"} hint={status.data && `${status.data.network} network`} />
      </div>
      <Card title="Peers">
        {peers.isPending ? <TableSkeleton /> : peers.isError ? <ErrorState error={peers.error} onRetry={() => void peers.refetch()} /> : peers.data.peers.length === 0
          ? <EmptyState title="No connected peers" hint="P2P may be disabled on this node (BLOCKFORGE_P2P_ENABLED) or no seeds are reachable. The API cannot distinguish these cases." /> : (
          <Table label="Peers"><thead><tr className="border-b border-line"><th className="th">Address</th><th className="th">Direction</th><th className="th text-right">Height</th><th className="th">Agent</th><th className="th text-right">Latency</th><th className="th text-right">In / out</th><th className="th">Connected</th></tr></thead>
            <tbody>{peers.data.peers.map((p) => (
              <tr key={p.address} className="border-b border-line/60 last:border-0">
                <td className="td font-mono text-xs">{p.address}</td><td className="td"><Badge tone={p.direction === "outbound" ? "info" : "ok"}>{p.direction}</Badge></td>
                <td className="td text-right">{p.height ?? "—"}</td><td className="td break-all text-xs">{p.user_agent ?? "—"}</td>
                <td className="td text-right">{p.latency_ms === null ? "—" : `${p.latency_ms} ms`}</td>
                <td className="td whitespace-nowrap text-right text-xs">{formatBytes(p.bytes_in)} / {formatBytes(p.bytes_out)}</td><td className="td whitespace-nowrap text-muted">{timeAgo(p.connected_at)}</td>
              </tr>))}</tbody></Table>)}
      </Card>
      <Card title="Connect to a peer">
        <AdminKeyNotice />
        <form className="mt-3 grid gap-3 sm:grid-cols-[1fr_8rem_auto] sm:items-end" noValidate onSubmit={f.handleSubmit((v) => connect.mutate(v))}>
          <div><label className="label" htmlFor="host">Host</label><input id="host" className="input" placeholder="203.0.113.5" {...f.register("host")} />{f.formState.errors.host && <p role="alert" className="mt-1 text-xs text-bad">{f.formState.errors.host.message}</p>}</div>
          <div><label className="label" htmlFor="port">P2P port</label><input id="port" inputMode="numeric" className="input" {...f.register("port")} />{f.formState.errors.port && <p role="alert" className="mt-1 text-xs text-bad">{f.formState.errors.port.message}</p>}</div>
          <button className="btn-primary" disabled={connect.isPending}>{connect.isPending ? <Spinner /> : "Connect"}</button>
        </form>
        <div className="mt-3 space-y-2">
          {connect.isError && <Notice tone="bad">{describeError(connect.error)}</Notice>}
          {connect.isSuccess && <Notice tone="ok">Dial started. The node does not report the outcome here; the peer appears in the list above if the handshake succeeds. Private addresses are refused unless the node sets BLOCKFORGE_ALLOW_PRIVATE_PEERS.</Notice>}
          <p className="text-xs text-muted">Disconnecting or banning peers is not supported by the backend API.</p>
        </div>
      </Card>
    </>
  );
}
