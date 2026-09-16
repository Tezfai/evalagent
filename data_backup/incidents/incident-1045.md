# Incident 1045: Recommendation Timeout Storm

- **Date:** 2025-03-08
- **Severity:** SEV-3
- **Status:** Resolved
- **Service:** recommendation-service
- **Related deployment:** deployment-885
- **Duration:** 22 minutes

## Summary
Homepage recommendation requests timed out for 11% of anonymous visitors. Checkout and catalog browsing remained available because recommendation calls are isolated behind a two-second deadline.

## Root cause
Deployment 885 enabled a new feature-vector join against the analytics warehouse for all traffic instead of the intended 5% experiment cohort. Warehouse query concurrency was exhausted and recommendation workers waited for database connections.

## Resolution
The feature flag was disabled, workers were restarted, and cached recommendations were served as a fallback. The release pipeline now requires an explicit cohort guard and warehouse load alert before increasing exposure.

## References
- [deployment-885](../deployments/deployment-885.md)
- [event-driven-platform](../architecture/event-driven-platform.md)
