# Event-Driven Commerce Platform

- **Last updated:** 2025-06-20
- **Owner:** Platform Reliability
- **Core technology:** Azure Service Bus, transactional outboxes, schema registry

## Topology
Checkout, payment, and inventory services write local transactions and outbox records. Publishers forward records to domain topics for fulfillment, notifications, analytics, and projections. Consumers use stable event IDs for idempotency.

## Delivery model
Delivery is at least once. Message locks, partition choice, retry limits, and dead-letter handling are part of each consumer's service-level design. Customer-visible events use dedicated topics so promotional or analytical bursts cannot starve them.

## Observability
Track oldest message age, active message count, lock-loss rate, redelivery count, dead-letter count, consumer lag, and publish-to-process duration. Queue depth alone is insufficient for incident detection.

## Known risks
Single partitions create head-of-line blocking, and processing time that exceeds lock duration causes repeated redelivery. See [incident-1049](../incidents/incident-1049.md), [incident-1050](../incidents/incident-1050.md), and [service-bus-delay-investigation](../engineering/service-bus-delay-investigation.md).
