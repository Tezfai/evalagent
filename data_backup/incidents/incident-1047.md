# Incident 1047: Payment API Latency

- **Date:** 2025-04-02
- **Severity:** SEV-2
- **Status:** Resolved
- **Service:** payment-service
- **Related deployment:** deployment-883
- **Duration:** 54 minutes

## Summary
Payment authorization p95 latency rose from 680 ms to 6.2 seconds, causing checkout retries and elevated duplicate-attempt protection responses. The acquirer was within its published error budget.

## Root cause
A logging change from deployment 883 added synchronous enrichment calls to the card-token vault for every authorization. Under normal volume this added 40 ms, but a vault rate limit caused exponential backoff inside payment worker threads.

## Resolution
The enrichment call was removed from the synchronous path, stuck workers were recycled, and delayed requests were reconciled using idempotency keys. The payment API now samples vault metadata asynchronously. See [payment-api-latency-analysis](../engineering/payment-api-latency-analysis.md).

## References
- [deployment-883](../deployments/deployment-883.md)
- [payment-runbook](../runbooks/payment-runbook.md)
- Related: [incident-1043](incident-1043.md)
