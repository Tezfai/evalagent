# Incident 1046: Checkout Database Connection Exhaustion

- **Date:** 2025-03-21
- **Severity:** SEV-1
- **Status:** Resolved
- **Service:** checkout-service
- **Related deployment:** deployment-886
- **Duration:** 39 minutes

## Summary
Checkout availability fell to 72% after the connection count on the order database reached its 600-connection limit. Requests failed with `SQLSTATE 53300` and order creation was intermittently unavailable.

## Root cause
Deployment 886 increased checkout worker concurrency from 8 to 20 without reducing the per-worker connection pool. A slow reporting query also held connections for up to 90 seconds, amplifying the exhaustion.

## Resolution
Traffic was shifted to the secondary checkout pool, concurrency was reverted, and the reporting query was terminated. Pool sizing is now calculated from the database connection budget during deployment review. See [database-connection-exhaustion](../engineering/database-connection-exhaustion.md).

## References
- [deployment-886](../deployments/deployment-886.md)
- [checkout-runbook](../runbooks/checkout-runbook.md)
- Related: [incident-1042](incident-1042.md)
