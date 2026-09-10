# Payment API Latency Analysis

- **Investigation date:** 2025-04-03
- **Owner:** Payments Engineering
- **Related incidents:** [incident-1047](../incidents/incident-1047.md), [incident-1043](../incidents/incident-1043.md)
- **Related deployment:** [deployment-883](../deployments/deployment-883.md)

## Evidence
Authorization p95 rose to 6.2 seconds while acquirer latency remained within its normal range. Worker traces showed repeated waits on a token-vault metadata call followed by exponential backoff. Wallet traffic was unaffected because it uses a separate adapter.

## Root cause
Audit enrichment was placed on the synchronous card authorization path. Vault throttling therefore consumed payment worker threads and increased retry pressure without improving authorization correctness.

## Resolution
Enrichment was removed from the request path and converted to an asynchronous sampled event. The payment service now has separate budgets for acquirer, vault, and internal processing latency. See [payment-runbook](../runbooks/payment-runbook.md).
