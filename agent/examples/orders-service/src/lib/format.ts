// Shared formatting helpers. They are not process activities and must not be
// extracted as such: no verb-object business construct, no actor, no ordering.

export function formatCurrency(amount: number, currency = "EUR") {
  return new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(amount);
}

export const parseAmount = (raw: string) => Number(raw.replace(/[^0-9.-]/g, ""));
