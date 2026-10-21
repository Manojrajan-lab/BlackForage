export type NetworkName = "dev" | "testnet" | "mainnet";

const NETWORKS: readonly NetworkName[] = ["dev", "testnet", "mainnet"];

function num(value: string | undefined, fallback: number, min: number): number {
  const n = Number(value);
  return Number.isFinite(n) && n >= min ? n : fallback;
}

const rawNetwork = (import.meta.env.VITE_NETWORK as string | undefined) ?? "dev";

export const config = {
  /** Default node URL. Users can override it in Settings (non-secret, stored locally). */
  defaultApiBaseUrl: ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://127.0.0.1:8000").replace(/\/+$/, ""),
  network: (NETWORKS.includes(rawNetwork as NetworkName) ? rawNetwork : "dev") as NetworkName,
  requestTimeoutMs: num(import.meta.env.VITE_REQUEST_TIMEOUT_MS as string | undefined, 10_000, 1_000),
  pollIntervalMs: num(import.meta.env.VITE_POLL_INTERVAL_MS as string | undefined, 5_000, 1_000),
} as const;
