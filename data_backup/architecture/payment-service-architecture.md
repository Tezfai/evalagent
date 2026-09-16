# Payment Service Architecture

- **Last updated:** 2025-06-18
- **Owner:** Payments Engineering
- **Runtime:** Java services on AKS with regional active-standby routing

## Responsibilities
Payment-service authorizes cards, captures funds, processes refunds, and records idempotency outcomes. Card data is handled by the token vault and never persisted in the commerce database.

## Request flow
Checkout submits a tokenized payment request. The service validates risk policy, calls the acquiring bank over private link, records the outcome in the idempotency ledger, and emits payment events. Wallet providers use a separate adapter path.

## Reliability boundaries
The acquirer and token vault are external latency boundaries. Certificate truststores are packaged with the runtime image. Synthetic authorization probes must test the complete path, including the regional standby alias.

## Known risks
Synchronous metadata calls can consume worker threads during vault throttling. Failover must preserve idempotency semantics. Historical failures: [incident-1043](../incidents/incident-1043.md), [incident-1047](../incidents/incident-1047.md), and [incident-1051](../incidents/incident-1051.md).
