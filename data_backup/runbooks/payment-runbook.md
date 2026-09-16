# Payment Service Runbook

- **Owner:** Payments Engineering
- **Last reviewed:** 2025-06-18
- **Service:** payment-service
- **Primary dependencies:** Acquirer, Token Vault, Key Vault, Private Link

## Trigger conditions
Use for authorization errors above 2%, TLS handshake failures, p95 above 2 seconds, or regional failover alarms. See [incident-1043](../incidents/incident-1043.md), [incident-1047](../incidents/incident-1047.md), and [incident-1051](../incidents/incident-1051.md).

## Response
1. Separate card, wallet, refund, and capture traffic by endpoint and region.
2. Test a synthetic authorization against the primary and standby endpoints.
3. Validate certificate and truststore fingerprints on the running process, not only mounted files.
4. Disable nonessential synchronous vault enrichment if worker backoff increases.
5. Route affected regions to the standby only after idempotency and acquirer capacity checks.
6. Reconcile retries from the idempotency ledger before replaying any authorization.

## Recovery criteria
Authorization success must exceed 99.7%, p95 must remain below 1.5 seconds, and the synthetic standby transaction must pass before failover is considered complete.
