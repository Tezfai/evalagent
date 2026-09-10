# Incident 1051: Payment Failover Readiness Gap

- **Date:** 2025-06-11
- **Severity:** SEV-1
- **Status:** Resolved
- **Service:** payment-service
- **Related deployment:** deployment-883
- **Duration:** 46 minutes

## Summary
A regional network impairment caused payment authorization errors for West Europe traffic. Automatic failover did not activate, and manual routing took 19 minutes.

## Root cause
The payment failover rule matched the primary endpoint hostname but not the private-link alias introduced during certificate remediation. Health probes remained green because they tested DNS resolution rather than a full authorization transaction.

## Resolution
Traffic was manually routed to the East US standby, failed authorizations were replayed safely using idempotency keys, and probes were upgraded to synthetic authorization checks. A quarterly failover exercise was added to the payment runbook.

## References
- [deployment-883](../deployments/deployment-883.md)
- [payment-runbook](../runbooks/payment-runbook.md)
- Related: [incident-1043](incident-1043.md)
