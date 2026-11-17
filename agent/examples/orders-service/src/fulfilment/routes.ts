import { Router } from "express";
import { approveOrder, shipOrder, submitOrder } from "./service";

const router = Router();

router.post("/orders", submitOrder);
router.post("/orders/:id/approve", approveOrder);
router.post("/orders/:id/ship", shipOrder);

export default router;
