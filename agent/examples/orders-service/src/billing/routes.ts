import { Router } from "express";
import { issueInvoice, placeCreditHold, retrieveInvoice } from "./service";

const router = Router();

// Invoice issuance is triggered when an order is confirmed.
router.post("/invoices", issueInvoice);

// Credit holds are applied when a customer exceeds the approved limit.
router.post("/invoices/:id/hold", placeCreditHold);

router.get("/invoices/:id", retrieveInvoice);

export default router;
