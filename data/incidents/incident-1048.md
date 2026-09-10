# Incident 1048: Redis Cluster Eviction Spike

- **Date:** 2025-04-18
- **Severity:** SEV-2
- **Status:** Resolved
- **Service:** checkout-service
- **Related deployment:** deployment-882
- **Duration:** 28 minutes

## Summary
Redis evictions increased to 34,000 per minute and checkout cache hit rate dropped from 96% to 61%. Database read traffic doubled, but no order data was lost because Redis stores derived session data only.

## Root cause
A hot-key mitigation from deployment 882 duplicated large cart payloads into a short-lived namespace. The namespace consumed 38% of cluster memory and its TTL policy was not applied after a serializer migration.

## Resolution
The namespace was purged, memory alerts were tuned, and the serializer was rolled back. Cart payloads now enforce a 64 KB size limit and hot-key handling uses request coalescing. See [redis-cache-runbook](../runbooks/redis-cache-runbook.md).

## References
- [deployment-882](../deployments/deployment-882.md)
- [redis-performance-investigation](../engineering/redis-performance-investigation.md)
- Related: [incident-1042](incident-1042.md)
