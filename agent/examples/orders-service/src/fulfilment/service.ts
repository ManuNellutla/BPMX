import { OrderBook } from "./order-book";

const book = new OrderBook();

export async function submitOrder(req, res) {
  const order = await book.create(req.body);
  res.status(201).json(order);
}

export async function approveOrder(req, res) {
  const order = await book.find(req.params.id);
  const approved = await book.checkCredit(order.customerId);
  if (!approved) {
    return res.status(402).json({ status: "credit_rejected" });
  }
  await book.setStatus(order.id, "approved");
  res.status(200).json({ status: "approved" });
}

export async function shipOrder(req, res) {
  await book.setStatus(req.params.id, "shipped");
  res.status(200).json({ status: "shipped" });
}
