import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Check, Copy, Inbox, Loader2, RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import { describeError } from "@/utils/errors";
import { truncateMiddle } from "@/utils/format";
import { cn } from "@/utils/cn";

export function Card({ title, action, children, className }: { title?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("card", className)}>
      {(title || action) && (
        <header className="flex items-center justify-between border-b border-line px-4 py-3">
          {title && <h2 className="text-sm font-semibold">{title}</h2>}
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, loading }: { label: string; value: ReactNode; hint?: ReactNode; loading?: boolean }) {
  return (
    <div className="card p-4">
      <div className="text-xs font-medium text-muted">{label}</div>
      {loading ? <Skeleton className="mt-2 h-7 w-24" /> : <div className="mt-1 break-all text-xl font-semibold">{value}</div>}
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export const Skeleton = ({ className }: { className?: string }) => (
  <div aria-hidden className={cn("animate-pulse rounded bg-line/60", className)} />
);

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return <div role="status" aria-label="Loading" className="space-y-2">{Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-8 w-full" />)}</div>;
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-bad/40 bg-bad/10 p-4 text-sm">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-bad" />
      <div className="min-w-0 flex-1">
        <p className="font-medium text-bad">Request failed</p>
        <p className="mt-1 break-words text-muted">{describeError(error)}</p>
      </div>
      {onRetry && <button className="btn-ghost shrink-0" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" />Retry</button>}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center text-muted">
      <Inbox className="h-8 w-8" aria-hidden />
      <p className="text-sm font-medium text-fg">{title}</p>
      {hint && <p className="max-w-md text-xs">{hint}</p>}
    </div>
  );
}

/** Honest placeholder for anything the backend cannot do. */
export function Unavailable({ title, reason, backendChange }: { title: string; reason: string; backendChange?: string }) {
  return (
    <div className="rounded-md border border-warn/40 bg-warn/10 p-4 text-sm">
      <p className="font-medium text-warn">{title}</p>
      <p className="mt-1 text-muted">{reason}</p>
      {backendChange && <p className="mt-2 text-xs text-muted"><span className="font-medium text-fg">Required backend change:</span> {backendChange}</p>}
    </div>
  );
}

export function Notice({ tone, children }: { tone: "info" | "warn" | "ok" | "bad"; children: ReactNode }) {
  const t = { info: "border-brand/40 bg-brand/10", warn: "border-warn/40 bg-warn/10", ok: "border-ok/40 bg-ok/10", bad: "border-bad/40 bg-bad/10" }[tone];
  return <div role={tone === "bad" ? "alert" : "status"} className={cn("rounded-md border p-3 text-sm", t)}>{children}</div>;
}

export function Spinner() { return <Loader2 className="h-4 w-4 animate-spin" aria-label="Loading" />; }

export function Badge({ tone = "info", children }: { tone?: "info" | "ok" | "warn" | "bad"; children: ReactNode }) {
  const t = { info: "bg-brand/15 text-brand", ok: "bg-ok/15 text-ok", warn: "bg-warn/15 text-warn", bad: "bg-bad/15 text-bad" }[tone];
  return <span className={cn("inline-flex items-center rounded px-2 py-0.5 text-xs font-medium", t)}>{children}</span>;
}

/** Truncated value with a full-value tooltip and copy button. */
export function CopyValue({ value, to, head = 10, tail = 8, full = false }: { value: string; to?: string; head?: number; tail?: number; full?: boolean }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => { if (!copied) return; const t = setTimeout(() => setCopied(false), 1500); return () => clearTimeout(t); }, [copied]);
  const text = full ? value : truncateMiddle(value, head, tail);
  return (
    <span className="inline-flex max-w-full items-center gap-1 align-middle">
      {to ? <Link to={to} title={value} className="min-w-0 break-all font-mono text-xs text-brand hover:underline">{text}</Link>
          : <span title={value} className="min-w-0 break-all font-mono text-xs">{text}</span>}
      <button type="button" aria-label={copied ? "Copied" : `Copy ${value}`} className="rounded p-1 text-muted hover:bg-line/50 hover:text-fg"
        onClick={() => { void navigator.clipboard?.writeText(value).then(() => setCopied(true)).catch(() => undefined); }}>
        {copied ? <Check className="h-3.5 w-3.5 text-ok" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </span>
  );
}

/** Accessible modal (native <dialog>: focus trap, Esc to close). */
export function Dialog({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) { if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", ""); }
    if (!open && d.open) { if (typeof d.close === "function") d.close(); else d.removeAttribute("open"); }
  }, [open]);
  return (
    <dialog ref={ref} aria-labelledby={id} onClose={onClose} onCancel={onClose}
      className="w-[min(32rem,calc(100vw-2rem))] rounded-lg border border-line bg-card p-0 text-fg backdrop:bg-black/60">
      {open && (
        <div className="p-5">
          <h2 id={id} className="text-base font-semibold">{title}</h2>
          <div className="mt-3">{children}</div>
        </div>
      )}
    </dialog>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-xl font-semibold">{title}</h1>{subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}</div>
      {actions}
    </div>
  );
}

export function KV({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1 border-b border-line/60 py-2 last:border-0 sm:grid-cols-[11rem_1fr] sm:gap-4">
      <dt className="text-xs font-medium text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-sm">{children}</dd>
    </div>
  );
}

export function Table({ children, label }: { children: ReactNode; label: string }) {
  return <div className="overflow-x-auto"><table aria-label={label} className="w-full min-w-[32rem] border-collapse">{children}</table></div>;
}
