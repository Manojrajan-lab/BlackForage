import { useState, type FormEvent } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Blocks, Coins, Gauge, LayoutDashboard, Menu, Moon, Network, Pickaxe, Search, Settings, Sun, Wallet, X, ArrowLeftRight } from "lucide-react";
import { useStatus, useChainGuard } from "@/hooks/queries";
import { useTheme } from "@/hooks/theme";
import { Notice } from "@/components/ui";
import { cn } from "@/utils/cn";
import { connection } from "@/api/client";
import { config } from "@/config";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/explorer", label: "Explorer", icon: Blocks },
  { to: "/transactions", label: "Transactions", icon: ArrowLeftRight },
  { to: "/wallet", label: "Wallet", icon: Wallet },
  { to: "/mining", label: "Mining", icon: Pickaxe },
  { to: "/network", label: "Network", icon: Network },
  { to: "/settings", label: "Settings", icon: Settings },
];

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav aria-label="Primary" className="flex flex-col gap-1">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} onClick={onNavigate}
          className={({ isActive }) => cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium", isActive ? "bg-brand/15 text-brand" : "text-muted hover:bg-line/40 hover:text-fg")}>
          <Icon className="h-4 w-4" aria-hidden />{label}
        </NavLink>
      ))}
    </nav>
  );
}

function SearchBox() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => { e.preventDefault(); const v = q.trim(); if (v) { nav(`/search?q=${encodeURIComponent(v)}`); setQ(""); } };
  return (
    <form onSubmit={submit} role="search" className="relative w-full max-w-md">
      <label htmlFor="global-search" className="sr-only">Search by block height, block hash, txid or address</label>
      <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted" aria-hidden />
      <input id="global-search" className="input pl-9" placeholder="Height, block hash, txid or address" value={q} onChange={(e) => setQ(e.target.value)} maxLength={130} />
    </form>
  );
}

function StatusPill() {
  const { data, isError, isPending } = useStatus();
  if (isPending) return <span className="text-xs text-muted">Connecting…</span>;
  if (isError) return <span className="flex items-center gap-2 text-xs text-bad"><span className="h-2 w-2 rounded-full bg-bad" />Node offline</span>;
  return <span className="flex items-center gap-2 text-xs text-muted"><span className="h-2 w-2 rounded-full bg-ok" />{data.network} · #{data.height}</span>;
}

export function AppLayout() {
  const [open, setOpen] = useState(false);
  const { theme, setTheme } = useTheme();
  const { mismatch } = useChainGuard();
  const { isError } = useStatus();
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[14rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-card focus:p-2">Skip to content</a>
      <aside className="hidden border-r border-line bg-card p-4 lg:block">
        <div className="mb-6 flex items-center gap-2 px-2 text-lg font-semibold"><Coins className="h-5 w-5 text-brand" aria-hidden />BlockForge</div>
        <NavLinks />
      </aside>
      <div className="min-w-0">
        <header className="sticky top-0 z-30 flex items-center gap-3 border-b border-line bg-card/95 px-4 py-3 backdrop-blur">
          <button className="btn-ghost lg:hidden" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}><Menu className="h-4 w-4" /></button>
          <SearchBox />
          <div className="ml-auto flex items-center gap-3"><StatusPill />
            <button className="btn-ghost" aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
          </div>
        </header>
        {open && (
          <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
            <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
            <div className="relative h-full w-64 bg-card p-4">
              <button className="btn-ghost mb-4" aria-label="Close menu" onClick={() => setOpen(false)}><X className="h-4 w-4" /></button>
              <NavLinks onNavigate={() => setOpen(false)} />
            </div>
          </div>
        )}
        <main id="main" className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
          {isError && <Notice tone="bad"><Gauge className="mr-2 inline h-4 w-4" aria-hidden />Cannot reach the node at <code className="font-mono">{connection.baseUrl}</code>. Start the backend and make sure this origin is listed in <code className="font-mono">BLOCKFORGE_CORS_ORIGINS</code> (default network: {config.network}).</Notice>}
          {mismatch && <Notice tone="warn">{mismatch}</Notice>}
          <Outlet />
        </main>
      </div>
    </div>
  );
}
