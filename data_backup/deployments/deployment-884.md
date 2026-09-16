# Deployment 884: Event-Driven Inventory Reservations

- **Date:** 2025-02-19
- **Service:** inventory-service
- **Environment:** production
- **Owner:** Supply Chain Systems
- **Change type:** Data consistency and throughput release
- **Status:** Reverted, redesign in progress
- **Related incidents:** [incident-1044](../incidents/incident-1044.md), [incident-1049](../incidents/incident-1049.md)

## Change summary
Moved reservation processing to Azure Service Bus consumers and added warehouse reconciliation to improve throughput during sales events.

## Observed impact
Messages were acknowledged before the reservation transaction committed, causing availability drift during a database failover. Later, long processing time exceeded the lock-renewal assumptions and created a large redelivery backlog.

## Resolution and follow-up
The acknowledgement order was corrected, consumer locks were aligned to the processing SLA, and poisoned messages are now isolated. The inventory team follows [inventory-runbook](../runbooks/inventory-runbook.md) for replay and reconciliation.
