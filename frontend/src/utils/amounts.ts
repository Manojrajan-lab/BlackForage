/** Exact decimal <-> base-unit conversion (1 BF = 10^8 units). No floats. Mirrors core/amounts.py. */
export const DECIMALS = 8;
export const COIN = 100_000_000n;
const MAX_U64 = (1n << 64n) - 1n;

export function toBaseUnits(text: string): bigint {
  const t = text.trim();
  if (!/^(\d+\.?\d*|\.\d+)$/.test(t)) throw new Error("Enter a plain non-negative decimal number");
  const [whole = "0", frac = ""] = t.split(".");
  if (frac.length > DECIMALS) throw new Error(`At most ${DECIMALS} decimal places`);
  const units = BigInt(whole || "0") * COIN + BigInt(frac.padEnd(DECIMALS, "0") || "0");
  if (units > MAX_U64) throw new Error("Amount too large");
  return units;
}

export function formatUnits(units: bigint | number): string {
  const u = typeof units === "bigint" ? units : BigInt(units);
  if (u < 0n) throw new Error("negative amount");
  const whole = u / COIN;
  const frac = (u % COIN).toString().padStart(DECIMALS, "0");
  return `${whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${frac}`;
}
