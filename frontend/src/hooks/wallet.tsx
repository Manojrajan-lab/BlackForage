import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from "react";
import { signTransfer, addressFromPublicKey, publicKeyOf, type SignedTransfer, type TransferInput } from "@/utils/txcodec";
import type { ChainParams } from "@/utils/chain";

/**
 * The private key lives only in a ref inside this provider (memory). It is never put in React state,
 * context value, storage, URLs or logs, and is zeroed on lock. Components can only ask it to sign.
 */
interface WalletApi {
  address: string | null;
  unlocked: boolean;
  unlock: (secret: Uint8Array, params: ChainParams) => string;
  sign: (params: ChainParams, t: TransferInput) => SignedTransfer;
  lock: () => void;
}

const Ctx = createContext<WalletApi | null>(null);

export function WalletProvider({ children }: { children: ReactNode }) {
  const secret = useRef<Uint8Array | null>(null);
  const [address, setAddress] = useState<string | null>(null);

  const lock = useCallback(() => { secret.current?.fill(0); secret.current = null; setAddress(null); }, []);
  const unlock = useCallback((s: Uint8Array, params: ChainParams) => {
    secret.current?.fill(0);
    secret.current = Uint8Array.from(s);
    const addr = addressFromPublicKey(publicKeyOf(secret.current), params.addressPrefix);
    setAddress(addr);
    return addr;
  }, []);
  const sign = useCallback((params: ChainParams, t: TransferInput) => {
    if (!secret.current) throw new Error("Wallet is locked");
    return signTransfer(secret.current, params, t);
  }, []);

  const value = useMemo(() => ({ address, unlocked: address !== null, unlock, sign, lock }), [address, unlock, sign, lock]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWallet(): WalletApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWallet outside WalletProvider");
  return v;
}
