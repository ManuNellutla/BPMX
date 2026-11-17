import { Ledger } from "./ledger";

const ledger = new Ledger();

export async function applyPayment(req, res) {
  const { invoiceId, amount, reference } = req.body;
  const matched = await ledger.matchRemittance(invoiceId, amount, reference);
  if (!matched) {
    return res.status(409).json({ status: "unmatched", invoiceId });
  }
  await ledger.postPayment(invoiceId, amount);
  res.status(200).json({ status: "applied", invoiceId });
}

export async function runDunning(req, res) {
  const overdue = await ledger.overdueInvoices(7);
  for (const invoice of overdue) {
    await ledger.sendReminder(invoice.id);
  }
  res.status(200).json({ reminded: overdue.length });
}

export async function escalateOverdueInvoice(req, res) {
  const invoice = await ledger.find(req.params.id);
  if (!invoice) return res.status(404).json({ status: "not_found" });
  await ledger.escalate(invoice.id);
  res.status(202).json({ status: "escalated" });
}
