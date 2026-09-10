# Redis Cache Runbook

- **Owner:** Platform Reliability
- **Last reviewed:** 2025-06-12
- **Scope:** Checkout cart and session cache

## Trigger conditions
Use for cache hit-rate collapse, eviction spikes, connection pool wait, memory fragmentation, or hot-key alerts. See [incident-1042](../incidents/incident-1042.md) and [incident-1048](../incidents/incident-1048.md).

## Response
1. Check memory used, evictions, fragmentation, command latency, hot keys, and pool wait by pod.
2. Confirm that only derived cart/session data is stored; never purge a keyspace containing source-of-truth data.
3. Disable oversized payload producers and enable request coalescing for hot keys.
4. Purge an offending namespace only after recording key counts and confirming database capacity.
5. Restore TTL policies and sample serialization size before re-enabling the feature flag.
6. Watch database read amplification while cache traffic recovers.

## Recovery criteria
Hit rate returns above 92%, evictions remain near zero, pool wait is below 50 ms, and database read traffic stays within its operating budget for 30 minutes.
