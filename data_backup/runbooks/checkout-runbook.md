# Checkout Service Runbook

- **Owner:** Commerce Platform
- **Last reviewed:** 2025-06-20
- **Service:** checkout-service
- **Primary dependencies:** Redis, Order Database, Payment API, Service Bus

## Trigger conditions
Use this runbook for checkout 5xx errors, p95 latency above 2 seconds, Redis pool saturation, database connection exhaustion, or delayed order confirmations. Relevant history: [incident-1042](../incidents/incident-1042.md), [incident-1046](../incidents/incident-1046.md), and [incident-1050](../incidents/incident-1050.md).

## Response
1. Confirm regional scope and compare request, Redis, database, and payment latency.
2. Check active deployments and freeze promotion if a release is within 30 minutes of onset.
3. If Redis pool wait exceeds 500 ms, enable cached-cart fallback and cap item lookups.
4. If database connections exceed 85% of budget, reduce worker concurrency before restarting pods.
5. For outbox delay, inspect oldest message age and move confirmation events to the dedicated topic.
6. Validate new orders, payment idempotency, and fulfillment publication before closing.

## Recovery criteria
Maintain observation for 30 minutes with checkout success above 99.5%, p95 below 1 second, and no growing outbox age.
