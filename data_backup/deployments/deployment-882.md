# Deployment 882: Checkout Session Fan-out

- **Date:** 2025-01-14
- **Service:** checkout-service
- **Environment:** production, US-East
- **Owner:** Commerce Platform
- **Change type:** Feature release
- **Status:** Rolled back
- **Related incidents:** [incident-1042](../incidents/incident-1042.md), [incident-1048](../incidents/incident-1048.md)

## Change summary
Introduced parallel cart-session lookups and hot-key mitigation to reduce checkout read latency. The release changed Redis serialization and added a per-item lookup path.

## Observed impact
The connection-per-lookup behavior saturated Redis pools and increased checkout p95 latency. A later serializer migration also caused oversized duplicate payloads and elevated evictions.

## Resolution and follow-up
Rolled back on 2025-01-14. The replacement release uses bounded connection reuse, request coalescing, a 64 KB cart limit, and a canary alert for Redis pool utilization. See [redis-cache-runbook](../runbooks/redis-cache-runbook.md).
