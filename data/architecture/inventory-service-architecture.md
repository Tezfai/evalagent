# Inventory Service Architecture

- **Last updated:** 2025-06-15
- **Owner:** Supply Chain Systems
- **Runtime:** Go consumers and API pods on AKS

## Responsibilities
Inventory-service owns stock balances, reservations, releases, and warehouse reconciliation. The warehouse ledger remains the external operational authority for physical counts.

## Request flow
Checkout requests a reservation. The service commits a reservation transaction, publishes an inventory event through the outbox, and consumers update availability projections. Warehouse adjustments arrive through Azure Service Bus and are applied by SKU sequence.

## Reliability boundaries
The transactional database is authoritative for reservations. Service Bus provides at-least-once delivery, so consumers must be idempotent. A message must not be acknowledged before the associated database commit succeeds.

## Known risks
Long reconciliation work can exceed message lock duration and produce redelivery storms. Database failover can expose acknowledgement ordering defects. See [incident-1044](../incidents/incident-1044.md), [incident-1049](../incidents/incident-1049.md), and [inventory-runbook](../runbooks/inventory-runbook.md).
