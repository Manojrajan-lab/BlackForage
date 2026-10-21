import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "@/api/endpoints";
import { Dialog, Notice, Spinner } from "@/components/ui";
import { useChainGuard } from "@/hooks/queries";
import { useWallet } from "@/hooks/wallet";
import { toBaseUnits, formatUnits } from "@/utils/amounts";
import { describeError } from "@/utils/errors";
import { decodeAddress } from "@/utils/txcodec";
import type { Account } from "@/types/api";
import { Link } from "react-router-dom";

const encoder = new TextEncoder();

export function SendForm({ account }: { account: Account }) {
  const wallet = useWallet();
  const qc = useQueryClient();
  const { params, mismatch } = useChainGuard();
  const [pending, setPending] = useState<{ to: string; amount: bigint; fee: bigint; memo: string } | null>(null);
  const [sent, setSent] = useState<string | null>(null);

  const schema = z.object({
    to: z.string().trim().refine((v) => decodeAddress(v, params.addressPrefix) !== null, "Not a valid address (prefix, length or checksum)"),
    amount: z.string().trim().superRefine((v, ctx) => {
      try { if (toBaseUnits(v) <= 0n) ctx.addIssue({ code: "custom", message: "Amount must be greater than zero" }); }
      catch (e) { ctx.addIssue({ code: "custom", message: (e as Error).message }); }
    }),
    fee: z.string().trim().superRefine((v, ctx) => {
      try { if (toBaseUnits(v) < params.minFee) ctx.addIssue({ code: "custom", message: `Minimum fee is ${formatUnits(params.minFee)} BF` }); }
      catch (e) { ctx.addIssue({ code: "custom", message: (e as Error).message }); }
    }),
    memo: z.string().refine((v) => encoder.encode(v).length <= params.maxMemoBytes, `Memo must be at most ${params.maxMemoBytes} bytes`),
  });
  type Values = z.infer<typeof schema>;
  const f = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { to: "", amount: "", fee: formatUnits(params.minFee), memo: "" } });

  const send = useMutation({
    mutationFn: async (p: NonNullable<typeof pending>) => {
      // Re-read the nonce at the last moment so a stale account snapshot cannot be signed.
      const fresh = await api.account(account.address);
      const total = p.amount + p.fee;
      // JSON numbers above 2^53 lose precision in JavaScript; only trust the local check when exact.
      if (Number.isSafeInteger(fresh.spendable) && BigInt(fresh.spendable) < total) throw new Error(`Insufficient spendable balance (${fresh.spendable_formatted} BF)`);
      const tx = wallet.sign(params, { recipientKeyHash: decodeAddress(p.to, params.addressPrefix)!, amount: p.amount, fee: p.fee, nonce: BigInt(fresh.next_nonce), memo: encoder.encode(p.memo) });
      const res = await api.submitTransaction(tx.hex);
      return res.txid;
    },
    onSuccess: async (txid) => {
      setSent(txid); setPending(null); f.reset();
      await qc.invalidateQueries();
    },
  });

  const review = f.handleSubmit((v) => { setSent(null); send.reset(); setPending({ to: v.to, amount: toBaseUnits(v.amount), fee: toBaseUnits(v.fee), memo: v.memo }); });
  const err = (k: keyof Values) => f.formState.errors[k] && <p role="alert" className="mt-1 text-xs text-bad">{f.formState.errors[k]!.message}</p>;

  return (
    <>
      <form onSubmit={review} className="space-y-3" noValidate>
        <div><label className="label" htmlFor="to">Recipient address</label><input id="to" className="input font-mono" autoComplete="off" spellCheck={false} {...f.register("to")} />{err("to")}</div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div><label className="label" htmlFor="amount">Amount (BF)</label><input id="amount" inputMode="decimal" className="input font-mono" placeholder="0.00000000" {...f.register("amount")} />{err("amount")}</div>
          <div><label className="label" htmlFor="fee">Fee (BF)</label><input id="fee" inputMode="decimal" className="input font-mono" {...f.register("fee")} />{err("fee")}</div>
        </div>
        <div><label className="label" htmlFor="memo">Memo (optional, public, on-chain)</label><input id="memo" className="input" maxLength={100} {...f.register("memo")} />{err("memo")}</div>
        <p className="text-xs text-muted">Spendable: <span className="font-mono">{account.spendable_formatted} BF</span>. Client-side checks are a convenience; the node performs the authoritative validation.</p>
        {sent && <Notice tone="ok">Submitted to the mempool. Txid <Link className="break-all font-mono text-xs text-brand hover:underline" to={`/tx/${sent}`}>{sent}</Link>. It is not confirmed until a block includes it.</Notice>}
        <button className="btn-primary" disabled={!!mismatch || send.isPending}>Review transaction</button>
      </form>

      <Dialog open={pending !== null} onClose={() => { if (!send.isPending) setPending(null); }} title="Confirm transaction">
        {pending && (
          <div className="space-y-3 text-sm">
            <dl className="space-y-2">
              <div><dt className="text-xs text-muted">To</dt><dd className="break-all font-mono text-xs">{pending.to}</dd></div>
              <div className="flex justify-between"><dt className="text-muted">Amount</dt><dd className="font-mono">{formatUnits(pending.amount)} BF</dd></div>
              <div className="flex justify-between"><dt className="text-muted">Fee</dt><dd className="font-mono">{formatUnits(pending.fee)} BF</dd></div>
              <div className="flex justify-between border-t border-line pt-2 font-semibold"><dt>Total debited</dt><dd className="font-mono">{formatUnits(pending.amount + pending.fee)} BF</dd></div>
              {pending.memo && <div><dt className="text-xs text-muted">Memo</dt><dd className="break-words">{pending.memo}</dd></div>}
            </dl>
            <Notice tone="warn">Transactions cannot be reversed once mined.</Notice>
            {send.isError && <Notice tone="bad">{describeError(send.error)}</Notice>}
            <div className="flex justify-end gap-2">
              <button className="btn-ghost" disabled={send.isPending} onClick={() => setPending(null)}>Cancel</button>
              <button className="btn-primary" disabled={send.isPending} onClick={() => send.mutate(pending)}>{send.isPending ? <><Spinner />Signing…</> : "Sign and send"}</button>
            </div>
          </div>
        )}
      </Dialog>
    </>
  );
}
