# Recommendation Service Architecture

- **Last updated:** 2025-03-12
- **Owner:** Personalization Engineering
- **Runtime:** Scala inference workers and feature API on AKS

## Responsibilities
The service produces ranked product recommendations for home, search, and campaign surfaces. It is advisory and must never block checkout or order creation.

## Request flow
The feature API reads online features from Redis and sends ranking requests to inference workers. Offline features are built in the analytics warehouse and published to a feature store. Anonymous traffic receives a cached recommendation when the live path exceeds its deadline.

## Reliability boundaries
Warehouse joins are asynchronous and must be protected by experiment cohort flags. The two-second recommendation deadline is enforced at the caller. Cache fallback is the expected behavior during model or feature-store degradation.

## Known risks
An incorrectly scoped experiment can exhaust warehouse concurrency. See [incident-1045](../incidents/incident-1045.md) and [deployment-885](../deployments/deployment-885.md).
