import { connection } from "@/api/client";

const KEY = "bf-api-url";

/** Only the (non-secret) node URL is persisted. The admin key and wallet keys never touch storage. */
export function loadSavedBaseUrl(): void {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved && isHttpUrl(saved)) connection.setBaseUrl(saved);
  } catch { /* storage unavailable */ }
}
export function saveBaseUrl(url: string): void {
  connection.setBaseUrl(url);
  try { localStorage.setItem(KEY, url.replace(/\/+$/, "")); } catch { /* storage unavailable */ }
}
export function isHttpUrl(v: string): boolean {
  try { const u = new URL(v); return u.protocol === "http:" || u.protocol === "https:"; } catch { return false; }
}
