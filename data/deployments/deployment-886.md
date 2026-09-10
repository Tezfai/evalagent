# Deployment 886: Checkout Worker Concurrency

- **Date:** 2025-03-21
- **Service:** checkout-service
- **Environment:** production, multi-region
- **Owner:** Commerce Platform
- **Change type:** Capacity tuning and outbox publisher release
- **Status:** Rolled back, publisher fix retained
- **Related incidents:** [incident-1046](../incidents/incident-1046.md), [incident-1050](../incidents/incident-1050.md)

## Change summary
Increased checkout worker concurrency from 8 to 20 and updated the order-event publisher used by fulfillment and customer notifications.

## Observed impact
The unchanged per-worker database pool exhausted the order database connection budget. A single Service Bus partition later delayed confirmation events behind promotion traffic.

## Resolution and follow-up
Concurrency was reverted, the reporting query was isolated, and confirmation events moved to a dedicated topic with age-based alerting. See [checkout-runbook](../runbooks/checkout-runbook.md) and [database-connection-exhaustion](../engineering/database-connection-exhaustion.md).
