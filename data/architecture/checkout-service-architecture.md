# Checkout Service Architecture

- **Last updated:** 2025-06-20
- **Owner:** Commerce Platform
- **Runtime:** Python API pods on AKS

## Responsibilities
Checkout validates carts, coordinates inventory reservation and payment authorization, writes orders, and publishes customer and fulfillment events. It does not own product availability or payment credentials.

## Request flow
The API reads cart sessions from Redis, calls inventory-service for reservation, calls payment-service with an idempotency key, commits the order to the Order Database, then writes an outbox event. A publisher sends outbox records to Service Bus topics.

## Reliability boundaries
Redis is a derived-data cache and may be bypassed. The Order Database is the source of truth. Payment and inventory calls have bounded deadlines and compensating actions. Connection pools must be sized against the database-wide connection budget, not per-pod CPU.

## Known risks
Large cart payloads increase Redis memory and serialization cost. Outbox partitioning affects confirmation latency. Historical failures: [incident-1042](../incidents/incident-1042.md), [incident-1046](../incidents/incident-1046.md), and [incident-1050](../incidents/incident-1050.md).
