export class OrderBook {
  private orders = new Map<string, Record<string, any>>();

  async create(payload: Record<string, any>) {
    const id = `ord_${this.orders.size + 1001}`;
    const order = { ...payload, id, status: "submitted" };
    this.orders.set(id, order);
    return order;
  }

  async find(id: string) {
    const order = this.orders.get(id);
    if (!order) throw new Error(`order not found: ${id}`);
    return order;
  }

  async checkCredit(customerId: string) {
    return Boolean(customerId);
  }

  async setStatus(id: string, status: string) {
    const order = this.orders.get(id);
    if (!order) throw new Error(`order not found: ${id}`);
    this.orders.set(id, { ...order, status });
  }
}
