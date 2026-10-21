import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "@/api/endpoints";
import { connection } from "@/api/client";
import { Badge, Card, KV, Notice, PageHeader, Spinner } from "@/components/ui";
import { isHttpUrl, saveBaseUrl } from "@/features/settings/storage";
import { useConnection } from "@/features/settings/AdminKeyNotice";
import { useChainGuard } from "@/hooks/queries";
import { useTheme } from "@/hooks/theme";
import { config } from "@/config";
import { describeError } from "@/utils/errors";

const urlSchema = z.object({ url: z.string().trim().refine(isHttpUrl, "Enter a full http:// or https:// URL") });
const keySchema = z.object({ key: z.string().min(16, "The node requires at least 16 characters") });

export function SettingsPage() {
  const qc = useQueryClient();
  const { theme, setTheme } = useTheme();
  const { baseUrl, hasKey } = useConnection();
  const { params, mismatch } = useChainGuard();
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const urlForm = useForm<z.infer<typeof urlSchema>>({ resolver: zodResolver(urlSchema), values: { url: baseUrl } });
  const keyForm = useForm<z.infer<typeof keySchema>>({ resolver: zodResolver(keySchema), defaultValues: { key: "" } });

  async function runTest() {
    setTesting(true); setTest(null);
    try { const h = await api.health(); setTest({ ok: true, text: `Connected. Node height ${h.height}.` }); }
    catch (e) { setTest({ ok: false, text: describeError(e) }); }
    finally { setTesting(false); }
  }

  return (
    <>
      <PageHeader title="Settings" />
      <Card title="Appearance">
        <div role="radiogroup" aria-label="Theme" className="flex gap-2">
          {(["dark", "light"] as const).map((t) => <button key={t} role="radio" aria-checked={theme === t} className={theme === t ? "btn-primary" : "btn-ghost"} onClick={() => setTheme(t)}>{t === "dark" ? "Dark" : "Light"}</button>)}
        </div>
      </Card>

      <Card title="Node connection">
        <form className="space-y-3" noValidate onSubmit={urlForm.handleSubmit(({ url }) => { saveBaseUrl(url); void qc.invalidateQueries(); })}>
          <div><label className="label" htmlFor="api-url">API base URL</label><input id="api-url" className="input font-mono" {...urlForm.register("url")} />
            {urlForm.formState.errors.url && <p role="alert" className="mt-1 text-xs text-bad">{urlForm.formState.errors.url.message}</p>}</div>
          <div className="flex gap-2"><button className="btn-primary">Save</button><button type="button" className="btn-ghost" disabled={testing} onClick={() => void runTest()}>{testing ? <Spinner /> : "Test connection"}</button></div>
          {test && <Notice tone={test.ok ? "ok" : "bad"}>{test.text}</Notice>}
        </form>
        <dl className="mt-4">
          <KV label="Configured network">{config.network} <span className="text-xs text-muted">(VITE_NETWORK; chain id {params.chainId})</span></KV>
          <KV label="Network check">{mismatch ? <Badge tone="bad">Mismatch</Badge> : <Badge tone="ok">OK</Badge>}</KV>
          <KV label="Polling interval">{config.pollIntervalMs / 1000}s <span className="text-xs text-muted">(VITE_POLL_INTERVAL_MS)</span></KV>
        </dl>
      </Card>

      <Card title="Admin API key">
        <p className="mb-3 text-sm text-muted">Needed only for starting/stopping mining and connecting peers. Held in memory for this tab; never saved to storage, URLs or build output. Reloading clears it.</p>
        <form className="space-y-3" noValidate onSubmit={keyForm.handleSubmit(({ key }) => { connection.setAdminKey(key); keyForm.reset(); })}>
          <div><label className="label" htmlFor="admin-key">API key</label><input id="admin-key" type="password" autoComplete="off" className="input" {...keyForm.register("key")} />
            {keyForm.formState.errors.key && <p role="alert" className="mt-1 text-xs text-bad">{keyForm.formState.errors.key.message}</p>}</div>
          <div className="flex items-center gap-2"><button className="btn-primary">Use key</button>
            {hasKey && <button type="button" className="btn-ghost" onClick={() => connection.setAdminKey("")}>Clear key</button>}
            {hasKey ? <Badge tone="ok">Key set</Badge> : <Badge tone="warn">No key</Badge>}</div>
        </form>
      </Card>

      <Card title="Backend capabilities and limits">
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
          <li>No endpoint to list all transactions, search addresses by prefix, or fetch historical difficulty beyond block headers.</li>
          <li>Pending transactions are not included in per-address history.</li>
          <li>The admin key is sent over whatever transport the URL uses; use HTTPS (via a reverse proxy) outside local development.</li>
          <li>The API has no user authentication; anyone who can reach it can read chain data and submit transactions.</li>
          <li>Consensus values used for signing (chain id, minimum fee) are copied into the frontend and checked against /v1/status.</li>
        </ul>
      </Card>
    </>
  );
}
