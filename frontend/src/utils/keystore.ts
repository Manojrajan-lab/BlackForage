import { scryptAsync } from "@noble/hashes/scrypt";
import { secp256k1 } from "@noble/curves/secp256k1";
import { z } from "zod";
import { bytesToHex, hexToBytes } from "./bytes";
import { addressFromPublicKey, publicKeyOf } from "./txcodec";

/** Compatible with blockforge/wallet/keystore.py (scrypt -> AES-256-GCM, address+pubkey bound as AAD). */
const MIN_N = 2 ** 14, MAX_N = 2 ** 20, R = 8, P = 1, DEFAULT_N = 2 ** 15, MIN_PASSWORD = 8;

const keystoreSchema = z.object({
  version: z.literal(1),
  address: z.string(),
  public_key: z.string(),
  kdf: z.object({ name: z.literal("scrypt"), n: z.number().int(), r: z.number().int(), p: z.number().int(), salt: z.string() }),
  cipher: z.object({ name: z.literal("aes-256-gcm"), nonce: z.string(), ciphertext: z.string() }),
});
export type KeystoreFile = z.infer<typeof keystoreSchema>;

const enc = new TextEncoder();
const aad = (address: string, pubkeyHex: string) => enc.encode(`BlockForge/keystore/v1|${address}|${pubkeyHex}`);
const buf = (u: Uint8Array): ArrayBuffer => u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength) as ArrayBuffer;

async function aesKey(password: string, salt: Uint8Array, n: number, usage: "encrypt" | "decrypt"): Promise<CryptoKey> {
  const raw = await scryptAsync(enc.encode(password), salt, { N: n, r: R, p: P, dkLen: 32 });
  return crypto.subtle.importKey("raw", buf(raw), "AES-GCM", false, [usage]);
}

export class KeystoreError extends Error {}

export function parseKeystore(text: string): KeystoreFile {
  let json: unknown;
  try { json = JSON.parse(text); } catch { throw new KeystoreError("Not a valid JSON file"); }
  const parsed = keystoreSchema.safeParse(json);
  if (!parsed.success) throw new KeystoreError("Not a BlockForge keystore file");
  return parsed.data;
}

/** Decrypts to the 32-byte secret. Caller must keep it in memory only. */
export async function decryptKeystore(file: KeystoreFile, password: string, prefix: string): Promise<Uint8Array> {
  const { n, r, p, salt } = file.kdf;
  if (n < MIN_N || n > MAX_N || r !== R || p !== P) throw new KeystoreError("Unsafe scrypt parameters");
  let secret: Uint8Array;
  try {
    const key = await aesKey(password, hexToBytes(salt), n, "decrypt");
    const plain = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: buf(hexToBytes(file.cipher.nonce)), additionalData: buf(aad(file.address, file.public_key)) },
      key, buf(hexToBytes(file.cipher.ciphertext)),
    );
    secret = new Uint8Array(plain);
  } catch {
    throw new KeystoreError("Wrong password or corrupted keystore");
  }
  if (secret.length !== 32 || !secp256k1.utils.isValidPrivateKey(secret)) throw new KeystoreError("Corrupt keystore");
  if (addressFromPublicKey(publicKeyOf(secret), prefix) !== file.address) {
    throw new KeystoreError("Keystore address does not match this network or key");
  }
  return secret;
}

export async function encryptKeystore(secret: Uint8Array, password: string, prefix: string, n = DEFAULT_N): Promise<KeystoreFile> {
  if (password.length < MIN_PASSWORD) throw new KeystoreError(`Password must be at least ${MIN_PASSWORD} characters`);
  if (n < MIN_N || n > MAX_N) throw new KeystoreError("scrypt cost out of range");
  const pub = publicKeyOf(secret);
  const address = addressFromPublicKey(pub, prefix);
  const pubHex = bytesToHex(pub);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const key = await aesKey(password, salt, n, "encrypt");
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv: buf(nonce), additionalData: buf(aad(address, pubHex)) }, key, buf(secret)));
  return {
    version: 1, address, public_key: pubHex,
    kdf: { name: "scrypt", n, r: R, p: P, salt: bytesToHex(salt) },
    cipher: { name: "aes-256-gcm", nonce: bytesToHex(nonce), ciphertext: bytesToHex(ct) },
  };
}

export function generateSecret(): Uint8Array {
  return secp256k1.utils.randomPrivateKey();
}
