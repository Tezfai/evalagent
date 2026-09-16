# Inventory Reservation Runbook

- **Owner:** Supply Chain Systems
- **Last reviewed:** 2025-06-15
- **Service:** inventory-service
- **Primary dependencies:** Inventory Database, Warehouse Ledger, Azure Service Bus

## Trigger conditions
Use for availability drift, reservation conflicts, event backlog, lock-loss redelivery, or warehouse reconciliation failures. See [incident-1044](../incidents/incident-1044.md) and [incident-1049](../incidents/incident-1049.md).

## Response
1. Pause high-risk reservations if database and warehouse counts disagree.
2. Compare committed reservation rows, warehouse ledger totals, and consumer offsets by SKU.
3. Inspect oldest message age, lock renewal failures, dead-letter count, and partition skew.
4. Scale consumers only after confirming the database can absorb the write rate.
5. Isolate poison messages, then replay valid events in SKU and sequence order.
6. Verify that the database transaction commits before the message is acknowledged.

## Recovery criteria
The backlog must trend down, oldest message age must be below five minutes, and a sampled SKU reconciliation must show zero unexplained variance.
