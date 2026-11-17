import { Router } from "express";
import { applyPayment, escalateOverdueInvoice } from "./service";

const router = Router();

// Remittance advice arrives from the bank feed.
router.post("/remittances", applyPayment);

router.post("/invoices/:id/escalate", escalateOverdueInvoice);

export default router;
