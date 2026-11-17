import { describe, expect, it } from "vitest";
import { formatCurrency, parseAmount } from "./format";

describe("format helpers", () => {
  it("formats currency", () => {
    expect(formatCurrency(12.5)).toContain("12.50");
  });

  it("parses amounts", () => {
    expect(parseAmount("EUR 1,200.00")).toBe(1200);
  });
});
