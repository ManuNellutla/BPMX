export class InvoiceRepository {
  private invoices = new Map<string, Record<string, unknown>>();

  async save(invoice: Record<string, unknown>) {
    const id = String(invoice.id ?? this.invoices.size + 1);
    this.invoices.set(id, { ...invoice, id });
    return id;
  }

  async updateStatus(id: string, status: string) {
    const invoice = this.invoices.get(id);
    if (!invoice) throw new Error(`invoice not found: ${id}`);
    this.invoices.set(id, { ...invoice, status });
  }

  async find(id: string) {
    return this.invoices.get(id) ?? null;
  }
}
