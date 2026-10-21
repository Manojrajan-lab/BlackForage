export function truncateMiddle(value: string, head = 10, tail = 8): string {
  return value.length <= head + tail + 1 ? value : `${value.slice(0, head)}…${value.slice(-tail)}`;
}

export function formatTimestamp(seconds: number): string {
  return new Date(seconds * 1000).toLocaleString();
}

export function timeAgo(seconds: number, nowMs: number = Date.now()): string {
  const diff = Math.max(0, Math.floor(nowMs / 1000 - seconds));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function formatNumber(n: number | bigint): string {
  return n.toLocaleString("en-US");
}

/** Compact large work values, e.g. 4.29e9 -> "4.29 G". */
export function formatWork(work: bigint): string {
  const units = ["", "K", "M", "G", "T", "P", "E"];
  let v = Number(work);
  let i = 0;
  while (v >= 1000 && i < units.length - 1) { v /= 1000; i++; }
  return `${v.toFixed(i === 0 ? 0 : 2)} ${units[i]}H`.replace("  ", " ");
}

const HEX64 = /^[0-9a-f]{64}$/;
export const isHash = (s: string): boolean => HEX64.test(s);
export const isHeight = (s: string): boolean => /^\d{1,12}$/.test(s);
