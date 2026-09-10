# Database Failover Runbook

- **Owner:** Database Reliability Engineering
- **Last reviewed:** 2025-05-30
- **Scope:** Checkout and inventory transactional databases

## Trigger conditions
Use for primary database unavailability, replication lag, connection exhaustion, or failed health probes. Related history includes [incident-1046](../incidents/incident-1046.md) and [incident-1044](../incidents/incident-1044.md).

## Response
1. Confirm whether the fault is connectivity, capacity, storage, or transaction corruption.
2. Capture active connections, long-running queries, replication lag, and last successful commit.
3. Stop noncritical reporting workloads before changing application routing.
4. Promote the replica only when replication state is known and the recovery point is accepted.
5. Update the connection alias, recycle application pools gradually, and watch write error rates.
6. Reconcile order, reservation, and outbox tables before restoring normal traffic.

## Recovery criteria
Replication is healthy, connection usage is below 70% of budget, writes succeed from two regions, and reconciliation has been signed off by the owning service team.
