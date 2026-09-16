# Incident 1043: Payment Authorization Errors

- **Date:** 2025-02-03
- **Severity:** SEV-1
- **Status:** Resolved
- **Service:** payment-service
- **Related deployment:** deployment-883
- **Duration:** 31 minutes

## Summary
Payment authorization failures reached 7.4% after a certificate rotation. Requests to the acquiring bank returned TLS handshake errors while wallet payments continued normally.

## Root cause
Deployment 883 mounted the new certificate bundle at `/etc/payment/certs`, but the Java truststore path remained pointed at the previous bundle. Only card authorization, which uses the external acquirer, was affected.

## Resolution
The incident commander halted the rollout, restored the previous truststore, and replayed failed authorizations from the idempotency ledger. Deployment validation now performs a live TLS handshake before promotion. See [payment-runbook](../runbooks/payment-runbook.md).

## References
- [deployment-883](../deployments/deployment-883.md)
- Related: [incident-1047](incident-1047.md)
