# Incident 1049: Inventory Event Backlog

- **Date:** 2025-05-06
- **Severity:** SEV-2
- **Status:** Resolved
- **Service:** inventory-service
- **Related deployment:** deployment-884
- **Duration:** 71 minutes

## Summary
Inventory reservation events reached a backlog of 1.8 million messages. Availability updates lagged by up to 26 minutes, resulting in conservative out-of-stock responses for high-demand products.

## Root cause
A Service Bus consumer deployment retained a ten-minute lock-renewal setting while processing time increased after warehouse reconciliation logic was added. Lock expirations caused repeated redelivery and starved healthy partitions.

## Resolution
Consumers were scaled from 12 to 30 instances, poisoned messages were isolated, and lock duration was aligned with the processing SLA. The team replayed events in SKU order and verified counts against the warehouse ledger.

## References
- [deployment-884](../deployments/deployment-884.md)
- [inventory-runbook](../runbooks/inventory-runbook.md)
- [service-bus-delay-investigation](../engineering/service-bus-delay-investigation.md)
- Related: [incident-1044](incident-1044.md)
