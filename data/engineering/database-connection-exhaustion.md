# Database Connection Exhaustion Analysis

- **Investigation date:** 2025-03-22
- **Owner:** Database Reliability Engineering
- **Related incident:** [incident-1046](../incidents/incident-1046.md)
- **Related deployment:** [deployment-886](../deployments/deployment-886.md)

## Evidence
The Order Database limit was 600 connections. Checkout worker count increased from 8 to 20 while each worker retained its prior pool size. Active connections reached 598, pool wait exceeded 12 seconds, and a reporting query held 74 connections for more than one minute.

## Root cause
Capacity was calculated from application worker CPU targets rather than the database connection budget. The reporting workload shared the transactional pool and had no maximum execution time.

## Resolution
Concurrency was reverted, the reporting query was terminated and isolated, and pool limits were recalculated across all regions. Deployment checks now reject a rollout when worst-case pool allocation exceeds 70% of the database budget.

## Operational reference
Use [database-failover-runbook](../runbooks/database-failover-runbook.md) for connection capture, workload isolation, and reconciliation.
