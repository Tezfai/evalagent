# Deployment 885: Recommendation Feature Vectors

- **Date:** 2025-03-08
- **Service:** recommendation-service
- **Environment:** production, 5% experiment cohort intended
- **Owner:** Personalization Engineering
- **Change type:** Experiment
- **Status:** Feature flag disabled
- **Related incident:** [incident-1045](../incidents/incident-1045.md)

## Change summary
Added a feature-vector join against the analytics warehouse to improve recommendation relevance for anonymous visitors.

## Observed impact
A missing cohort guard enabled the query for all traffic. Warehouse concurrency was exhausted, recommendation workers timed out, and the checkout surface received fallback recommendations.

## Resolution and follow-up
The flag was disabled and cached recommendations restored. Future promotions require cohort verification, warehouse concurrency budgets, and a rollback threshold before exposure increases.
