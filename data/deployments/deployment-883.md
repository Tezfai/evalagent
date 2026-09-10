# Deployment 883: Payment Truststore and Audit Enrichment

- **Date:** 2025-02-03
- **Service:** payment-service
- **Environment:** production, multi-region
- **Owner:** Payments Engineering
- **Change type:** Security and observability release
- **Status:** Partially reverted
- **Related incidents:** [incident-1043](../incidents/incident-1043.md), [incident-1047](../incidents/incident-1047.md), [incident-1051](../incidents/incident-1051.md)

## Change summary
Rotated the acquiring-bank certificate bundle, updated payment audit logging, and introduced vault metadata enrichment for authorization events.

## Observed impact
The truststore path was not updated in the Java runtime, producing TLS failures for card authorization. Synchronous vault enrichment later caused worker backoff and high authorization latency. The private-link alias also exposed a failover probe gap.

## Resolution and follow-up
The truststore was restored, synchronous enrichment was removed, and synthetic authorization probes now validate both primary and standby endpoints. See [payment-runbook](../runbooks/payment-runbook.md).
