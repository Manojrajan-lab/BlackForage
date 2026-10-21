import { describe, expect, it } from "vitest";
import { formatUnits, toBaseUnits } from "@/utils/amounts";
import { bitsToTarget, difficultyFromBits, POW_LIMIT, workFromBits } from "@/utils/chain";
import { formatBytes, isHash, isHeight, timeAgo, truncateMiddle } from "@/utils/format";

describe("amounts", () => {
  it("parses decimals exactly", () => {
    expect(toBaseUnits("1.5")).toBe(150_000_000n);
    expect(toBaseUnits("0.00000001")).toBe(1n);
    expect(toBaseUnits(".5")).toBe(50_000_000n);
    expect(toBaseUnits("7")).toBe(700_000_000n);
  });
  it("rejects bad input", () => {
    for (const bad of ["", "-1", "1e3", "1.123456789", "abc", "1.2.3", "99999999999999999999"]) {
      expect(() => toBaseUnits(bad), bad).toThrow();
    }
  });
  it("formats like the backend", () => {
    expect(formatUnits(150_000_000)).toBe("1.50000000");
    expect(formatUnits(5_000_000_000n)).toBe("50.00000000");
    expect(formatUnits(123_456_789_000_000n)).toBe("1,234,567.89000000");
  });
});

describe("chain math", () => {
  it("decodes compact bits", () => {
    expect(bitsToTarget(0x2000ffff)).toBe(POW_LIMIT);
    expect(bitsToTarget(0x20800000)).toBe(0n); // sign bit => invalid
  });
  it("difficulty is 1 at the pow limit and grows as target shrinks", () => {
    expect(difficultyFromBits(0x2000ffff)).toBe(1);
    expect(difficultyFromBits(0x1f00ffff)).toBeGreaterThan(200);
    expect(workFromBits(0x2000ffff)).toBeGreaterThan(0n);
  });
});

describe("format", () => {
  it("truncates and validates", () => {
    expect(truncateMiddle("a".repeat(64))).toBe(`${"a".repeat(10)}…${"a".repeat(8)}`);
    expect(truncateMiddle("short")).toBe("short");
    expect(isHash("a".repeat(64))).toBe(true);
    expect(isHash("A".repeat(64))).toBe(false);
    expect(isHeight("42")).toBe(true);
    expect(isHeight("4x")).toBe(false);
  });
  it("formats time and size", () => {
    expect(timeAgo(1000, 1_030_000)).toBe("30s ago");
    expect(timeAgo(0, 7_200_000)).toBe("2h ago");
    expect(formatBytes(2048)).toBe("2.0 KB");
  });
});
