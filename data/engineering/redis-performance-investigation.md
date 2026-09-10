# Redis Performance Investigation

- **Investigation date:** 2025-04-19
- **Owner:** Platform Reliability
- **Scope:** Checkout Redis cluster
- **Related incidents:** [incident-1042](../incidents/incident-1042.md), [incident-1048](../incidents/incident-1048.md)

## Evidence
During incident 1042, pool wait correlated with cart item count and connections peaked at the configured per-pod limit. During incident 1048, memory grew after the hot-key namespace began storing duplicate serialized carts. Eviction and database read amplification rose together.

## Root cause
The checkout release combined unbounded parallel lookups with a serializer migration that bypassed namespace TTL application. Both changes increased Redis work and reduced effective cache capacity.

## Corrective actions
Connection reuse and request coalescing were implemented, cart payloads were capped at 64 KB, and TTL validation was added to canary checks. Alerts now cover pool wait, command latency, evictions, and memory fragmentation. The [redis-cache-runbook](../runbooks/redis-cache-runbook.md) defines the operational response.
