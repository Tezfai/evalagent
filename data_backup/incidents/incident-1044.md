# Incident 1044: Inventory Reservation Drift

- **Date:** 2025-02-19
- **Severity:** SEV-2
- **Status:** Resolved
- **Service:** inventory-service
- **Related deployment:** deployment-884
- **Duration:** 64 minutes

## Summary
The inventory API reported stale availability for 2.1% of SKU queries, allowing checkout to reserve items that had already sold out. No duplicate shipments were created, but 183 orders required customer outreach.

## Root cause
Deployment 884 changed reservation events from synchronous writes to asynchronous publication. A retry policy on the event consumer acknowledged messages before the database transaction committed, creating a lag window during failover of the primary inventory database.

## Resolution
Engineering paused reservations, replayed the dead-letter queue, reconciled stock against the warehouse ledger, and reverted the acknowledgement change. The corrected design commits the reservation before acknowledging the event.

## References
- [deployment-884](../deployments/deployment-884.md)
- [inventory-runbook](../runbooks/inventory-runbook.md)
- Related: [incident-1049](incident-1049.md)
