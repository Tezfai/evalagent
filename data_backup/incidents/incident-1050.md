# Incident 1050: Checkout Order Confirmation Delay

- **Date:** 2025-05-23
- **Severity:** SEV-3
- **Status:** Resolved
- **Service:** checkout-service
- **Related deployment:** deployment-886
- **Duration:** 36 minutes

## Summary
Orders completed successfully, but confirmation emails and fulfillment notifications were delayed by up to 18 minutes. Customers saw completed orders in the account portal, limiting duplicate submissions.

## Root cause
The checkout outbox publisher used a single Service Bus partition and processed a burst of promotion events ahead of order confirmations. There was no age-based priority for customer-visible events.

## Resolution
The backlog was drained after adding four publisher workers. Order confirmation events now use a dedicated topic and alerting is based on oldest message age rather than queue depth alone.

## References
- [deployment-886](../deployments/deployment-886.md)
- [checkout-runbook](../runbooks/checkout-runbook.md)
- Related: [incident-1049](incident-1049.md)
