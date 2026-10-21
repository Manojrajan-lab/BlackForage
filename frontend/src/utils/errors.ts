import { ApiError } from "@/api/client";

/** Turn backend error codes into plain-language guidance. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "admin-disabled": return "Admin API is disabled on this node. Set BLOCKFORGE_API_KEY (16+ chars) and restart it.";
      case "unauthorized": return "Admin API key rejected by the node.";
      case "no-admin-key": return err.message;
      case "rate-limited": return "Rate limit reached. Wait a moment and retry.";
      case "mempool-duplicate": return "This transaction is already in the mempool.";
      case "mempool-stale-nonce": return "Nonce already used. Refresh your account and try again.";
      case "mempool-nonce-gap": return "Nonce is ahead of the account's next nonce.";
      case "p2p-disabled": return "P2P networking is disabled on this node.";
      default: return err.message;
    }
  }
  return err instanceof Error ? err.message : "Unknown error";
}
