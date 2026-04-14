## ADDED Requirements

### Requirement: Live execution SHALL create explicit order intents
Before any non-dry-run broker submission occurs, the engine SHALL create an `OrderIntent` record with a stable intent identifier, requested symbol, side, quantity, originating target context, and execution mode.

#### Scenario: Intent created before submit
- **WHEN** `qexec rebalance <targets.json> --execute` prepares a live or paper order
- **THEN** the engine persists an order intent record before submitting any broker order

### Requirement: Broker orders and fill events SHALL be tracked separately from intents
Each broker submission SHALL create a broker-order record linked to an order intent or parent order, and each status or fill update SHALL be stored as a separate execution event rather than overwriting the original intent data.

#### Scenario: Partial fill recorded as event
- **WHEN** a submitted broker order receives a partial fill update
- **THEN** the engine records a fill event, updates aggregated filled quantity, and keeps the original intent and broker-order identifiers intact

### Requirement: Order submission SHALL be idempotent and replay-safe
The engine SHALL use stable intent or child-order identifiers to prevent duplicate broker submissions across retries, timeouts, or process restarts, and SHALL reconcile existing broker state before issuing a replacement submission when prior delivery is uncertain.

#### Scenario: Retry after uncertain submit outcome
- **WHEN** a submit attempt times out and the engine cannot tell whether the broker accepted the order
- **THEN** the engine checks persisted state and broker open orders before deciding whether to reuse existing order state or submit a new broker order

### Requirement: Active execution state SHALL be recoverable and reconcilable
The engine SHALL persist enough state to resume active execution after restart, including active parent orders, child orders, remaining quantity, last reconcile time, and known fill progress, and startup or explicit recovery SHALL query broker state to repair local state before new execution continues.

#### Scenario: Restart during active parent order
- **WHEN** the process restarts while a parent order is partially filled
- **THEN** the engine reconciles broker open orders and fills, restores remaining quantity, and resumes or stops execution according to the reconciled state

### Requirement: Parent orders SHALL track child-order progress
The engine SHALL represent higher-level execution goals as parent orders with remaining quantity or value and linked child-order history so single-run or multi-run slicing can be measured and continued.

#### Scenario: Remaining quantity after first child order
- **WHEN** a child order completes without fully satisfying its parent order
- **THEN** the parent order remains open with updated remaining quantity and a linked record of the completed or active child order
