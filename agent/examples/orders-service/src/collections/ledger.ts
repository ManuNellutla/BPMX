import { Ledger } from "./ledger";

export class Ledger {
  private payments: string[] = [];

  async matchRemittance(invoiceId: string, amount: number, reference: string) {
    return Boolean(invoiceId && amount > 0 && reference);
  }

  async postPayment(invoiceId: string, amount: number) {
    this.payments.push(`${invoiceId}:${amount}`);
  }

  async overdueInvoices(days: number) {
    return [{ id: "inv_1042", daysOverdue: days + 3 }];
  }

  async sendReminder(invoiceId: string) {
    this.payments.push(`reminder:${invoiceId}`);
  }

  async find(invoiceId: string) {
    return { id: invoiceId, status: "overdue" };
  }

  async escalate(invoiceId: string) {
    this.payments.push(`escalated:${invoiceId}`);
  }
}
