import { InvoiceRepository } from "./repository";

const repository = new InvoiceRepository();

const taxFor = (amount: number) => Math.round(amount * 0.19 * 100) / 100;

export async function issueInvoice(req, res) {
  const order = req.body;
  const invoice = {
    customerId: order.customerId,
    amount: order.amount + taxFor(order.amount),
    dueDate: order.dueDate,
    status: "issued",
  };
  await repository.save(invoice);
  res.status(201).json(invoice);
}

export async function placeCreditHold(req, res) {
  await repository.updateStatus(req.params.id, "credit_hold");
  res.status(202).json({ status: "credit_hold" });
}
