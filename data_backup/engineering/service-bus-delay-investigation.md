# Service Bus Delay Investigation

- **Investigation date:** 2025-05-07
- **Owner:** Platform Reliability and Supply Chain Systems
- **Related incidents:** [incident-1049](../incidents/incident-1049.md), [incident-1050](../incidents/incident-1050.md)
- **Related deployment:** [deployment-884](../deployments/deployment-884.md)

## Evidence
Inventory backlog reached 1.8 million messages and oldest message age reached 26 minutes. Consumer traces showed lock loss during warehouse reconciliation, followed by redelivery. Checkout confirmation events were delayed separately when promotion events shared their partition.

## Root cause
Consumer processing time exceeded the lock-renewal assumption, while a single partition created head-of-line blocking for unrelated event classes. Queue depth did not identify the customer-visible delay early enough.

## Resolution
Consumers were scaled after database capacity checks, invalid messages were dead-lettered, and inventory events were replayed in sequence. Confirmation events moved to a dedicated topic with alerts on oldest message age.

## Operational reference
Use [inventory-runbook](../runbooks/inventory-runbook.md) for replay and reconciliation, and [event-driven-platform](../architecture/event-driven-platform.md) for topology and observability standards.
