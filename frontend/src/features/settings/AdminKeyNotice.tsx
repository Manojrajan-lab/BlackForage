import { Link } from "react-router-dom";
import { connection } from "@/api/client";
import { useSyncExternalStore } from "react";
import { Notice } from "@/components/ui";

export function useConnection() {
  const baseUrl = useSyncExternalStore(connection.subscribe, () => connection.baseUrl);
  const hasKey = useSyncExternalStore(connection.subscribe, () => connection.hasAdminKey);
  return { baseUrl, hasKey };
}

export function AdminKeyNotice() {
  const { hasKey } = useConnection();
  if (hasKey) return null;
  return <Notice tone="info">Node-control actions need the admin API key (<code className="font-mono">BLOCKFORGE_API_KEY</code>). Enter it in <Link className="text-brand underline" to="/settings">Settings</Link>; it is kept in memory only.</Notice>;
}
