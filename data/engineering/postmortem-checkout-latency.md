# Postmortem: Checkout Latency and Availability

- **Date:** 2025-03-24
- **Authors:** Commerce Platform and Database Reliability
- **Related incidents:** [incident-1042](../incidents/incident-1042.md), [incident-1046](../incidents/incident-1046.md), [incident-1050](../incidents/incident-1050.md)

## Summary
Two releases created separate checkout failure modes: Redis saturation increased latency, while worker concurrency exhausted database connections. A third effect delayed confirmations through a shared event partition.

## Root causes
The release process evaluated pod-level capacity without accounting for shared Redis and database budgets. Outbox traffic was also partitioned by publisher rather than customer-visible event class.

## Resolution
Deployment 886 was rolled back for concurrency, confirmation events moved to a dedicated topic, and checkout can now switch to cache and payment degradation modes independently. Pool sizing and outbox age are required release review inputs.

## Follow-up
The [checkout-runbook](../runbooks/checkout-runbook.md) and [checkout-service-architecture](../architecture/checkout-service-architecture.md) are the canonical operational and design references.
