# Incident 1042: Checkout API Latency

- **Date:** 2025-01-14
- **Severity:** SEV-2
- **Status:** Resolved
- **Service:** checkout-service
- **Related deployment:** deployment-882
- **Duration:** 47 minutes

## Summary
Checkout p95 latency increased from 420 ms to 3.8 seconds for approximately 18% of requests in the US-East region. Cart reads and payment authorization were healthy, but checkout requests accumulated behind a saturated Redis connection pool.

## Root cause
Deployment 882 increased cart-session fan-out and introduced a cache miss path that opened one Redis connection per item lookup. The pool limit remained at 50 connections per pod, causing queueing and connection timeouts under peak traffic.

## Resolution
The on-call rolled back deployment 882, raised the pool limit temporarily, and drained affected pods. Platform engineering later shipped bounded connection reuse and a per-request lookup cap. See [redis-performance-investigation](../engineering/redis-performance-investigation.md) and [redis-cache-runbook](../runbooks/redis-cache-runbook.md).

## References
- [deployment-882](../deployments/deployment-882.md)
- Related: [incident-1048](incident-1048.md)
