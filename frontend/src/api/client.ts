import type { ZodType } from "zod";
import { config } from "@/config";

/** Normalised failure for every kind of API problem. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly kind: "network" | "timeout" | "http" | "malformed",
    public readonly status?: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
  /** Failures worth retrying automatically (never 4xx). */
  get retryable(): boolean {
    return this.kind === "network" || this.kind === "timeout" || (this.status !== undefined && this.status >= 500);
  }
}

interface Connection {
  baseUrl: string;
  /** Admin key lives in memory only: never persisted, never in a URL. */
  adminKey: string;
}

const conn: Connection = { baseUrl: config.defaultApiBaseUrl, adminKey: "" };
const listeners = new Set<() => void>();

export const connection = {
  get baseUrl() { return conn.baseUrl; },
  get hasAdminKey() { return conn.adminKey.length > 0; },
  setBaseUrl(url: string) { conn.baseUrl = url.replace(/\/+$/, ""); listeners.forEach((l) => l()); },
  setAdminKey(key: string) { conn.adminKey = key; listeners.forEach((l) => l()); },
  subscribe(l: () => void) { listeners.add(l); return () => { listeners.delete(l); }; },
};

interface RequestOptions<T> {
  method?: "GET" | "POST";
  body?: unknown;
  schema: ZodType<T>;
  admin?: boolean;
  signal?: AbortSignal;
}

export async function request<T>(path: string, opts: RequestOptions<T>): Promise<T> {
  const { method = "GET", body, schema, admin = false, signal } = opts;
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (admin) {
    if (!conn.adminKey) throw new ApiError("Admin API key not set. Enter it in Settings.", "http", 401, "no-admin-key");
    headers["X-API-Key"] = conn.adminKey;
  }

  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), config.requestTimeoutMs);
  const onAbort = () => timeout.abort();
  signal?.addEventListener("abort", onAbort);

  let res: Response;
  try {
    res = await fetch(`${conn.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: timeout.signal,
      credentials: "omit",
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    if (timeout.signal.aborted) throw new ApiError("Request timed out", "timeout");
    throw new ApiError(`Cannot reach node at ${conn.baseUrl}. Is it running, and is this origin in BLOCKFORGE_CORS_ORIGINS?`, "network");
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }

  let payload: unknown;
  try {
    payload = await res.json();
  } catch {
    if (!res.ok) throw new ApiError(`HTTP ${res.status}`, "http", res.status);
    throw new ApiError("Node returned a non-JSON response", "malformed", res.status);
  }

  if (!res.ok) {
    const e = (payload as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(e?.message ?? `HTTP ${res.status}`, "http", res.status, e?.code);
  }

  const parsed = schema.safeParse(payload);
  if (!parsed.success) {
    throw new ApiError("Node response did not match the expected schema", "malformed", res.status);
  }
  return parsed.data;
}
