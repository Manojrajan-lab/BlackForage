import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Download } from "lucide-react";
import { Card, Notice, Spinner } from "@/components/ui";
import { useWallet } from "@/hooks/wallet";
import { useChainGuard } from "@/hooks/queries";
import { decryptKeystore, encryptKeystore, generateSecret, KeystoreError, parseKeystore, type KeystoreFile } from "@/utils/keystore";
import { addressFromPublicKey, publicKeyOf } from "@/utils/txcodec";

const MAX_FILE = 16 * 1024;

const importSchema = z.object({ password: z.string().min(1, "Enter the keystore password") });
const createSchema = z.object({
  password: z.string().min(8, "At least 8 characters"),
  confirm: z.string(),
}).refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });

function download(file: KeystoreFile) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(file, null, 2)], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url; a.download = `blockforge-${file.address.slice(0, 10)}.json`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ImportCard() {
  const { unlock } = useWallet();
  const { params, mismatch } = useChainGuard();
  const [file, setFile] = useState<KeystoreFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const f = useForm<z.infer<typeof importSchema>>({ resolver: zodResolver(importSchema) });

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    setError(null); setFile(null);
    const picked = e.target.files?.[0];
    if (!picked) return;
    if (picked.size > MAX_FILE) { setError("File is too large to be a keystore"); return; }
    try { setFile(parseKeystore(await picked.text())); } catch (err) { setError(err instanceof Error ? err.message : "Cannot read file"); }
  }

  const submit = f.handleSubmit(async ({ password }) => {
    if (!file) return;
    setError(null);
    try {
      unlock(await decryptKeystore(file, password, params.addressPrefix), params);
      f.reset(); setFile(null);
    } catch (err) { setError(err instanceof KeystoreError ? err.message : "Could not unlock wallet"); }
  });

  return (
    <Card title="Open an existing wallet">
      <p className="mb-3 text-sm text-muted">Select the encrypted keystore file created by <code className="font-mono">blockforge-wallet new</code> or by this app. Decryption happens in your browser; nothing is uploaded.</p>
      <form onSubmit={submit} className="space-y-3" noValidate>
        <div><label className="label" htmlFor="ks-file">Keystore file (.json)</label><input id="ks-file" type="file" accept="application/json,.json" className="input" onChange={onFile} /></div>
        {file && <p className="break-all font-mono text-xs text-muted">{file.address}</p>}
        <div><label className="label" htmlFor="ks-pass">Password</label><input id="ks-pass" type="password" autoComplete="off" className="input" {...f.register("password")} />
          {f.formState.errors.password && <p role="alert" className="mt-1 text-xs text-bad">{f.formState.errors.password.message}</p>}</div>
        {error && <Notice tone="bad">{error}</Notice>}
        <button className="btn-primary" disabled={!file || f.formState.isSubmitting || !!mismatch}>{f.formState.isSubmitting ? <><Spinner />Decrypting…</> : "Unlock"}</button>
      </form>
    </Card>
  );
}

function CreateCard() {
  const { unlock } = useWallet();
  const { params, mismatch } = useChainGuard();
  const [created, setCreated] = useState<KeystoreFile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const f = useForm<z.infer<typeof createSchema>>({ resolver: zodResolver(createSchema) });

  const submit = f.handleSubmit(async ({ password }) => {
    setError(null);
    const secret = generateSecret();
    try {
      const file = await encryptKeystore(secret, password, params.addressPrefix);
      setCreated(file);
      download(file);
      unlock(secret, params);
      f.reset();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not create wallet"); }
    finally { secret.fill(0); }
  });

  return (
    <Card title="Create a new wallet">
      <p className="mb-3 text-sm text-muted">Generates a random secp256k1 key in this browser and saves it as a password-encrypted keystore file (scrypt + AES-256-GCM, same format as the Python CLI).</p>
      <Notice tone="warn">There is no seed phrase and no recovery. If you lose the downloaded file or its password, the funds are gone. This app does not store your key anywhere.</Notice>
      <form onSubmit={submit} className="mt-3 space-y-3" noValidate>
        <div><label className="label" htmlFor="new-pass">Password (min 8 characters)</label><input id="new-pass" type="password" autoComplete="new-password" className="input" {...f.register("password")} />
          {f.formState.errors.password && <p role="alert" className="mt-1 text-xs text-bad">{f.formState.errors.password.message}</p>}</div>
        <div><label className="label" htmlFor="new-confirm">Repeat password</label><input id="new-confirm" type="password" autoComplete="new-password" className="input" {...f.register("confirm")} />
          {f.formState.errors.confirm && <p role="alert" className="mt-1 text-xs text-bad">{f.formState.errors.confirm.message}</p>}</div>
        {error && <Notice tone="bad">{error}</Notice>}
        <button className="btn-primary" disabled={f.formState.isSubmitting || !!mismatch}>{f.formState.isSubmitting ? <><Spinner />Encrypting…</> : "Create and download keystore"}</button>
      </form>
      {created && <div className="mt-3"><Notice tone="ok">Wallet created: <span className="break-all font-mono text-xs">{created.address}</span>. Make sure the downloaded file is backed up.{" "}
        <button className="inline-flex items-center gap-1 text-brand hover:underline" onClick={() => download(created)}><Download className="h-3 w-3" />Download again</button></Notice></div>}
    </Card>
  );
}

export function CreateOrImport() {
  return <div className="grid gap-4 lg:grid-cols-2"><ImportCard /><CreateCard /></div>;
}

/** Exposed for tests: address a freshly generated key would have. */
export const addressOfSecret = (s: Uint8Array, prefix: string) => addressFromPublicKey(publicKeyOf(s), prefix);
