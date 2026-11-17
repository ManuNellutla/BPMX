import cron from "node-cron";
import { runDunning } from "./service";

// Dunning runs every night at 02:00.
cron.schedule("0 2 * * *", runDunning);
