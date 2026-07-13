# pyright: strict
"""Durable orchestration around the framework-neutral execution transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .domain import Fill, OrderEvent, OrderIntent, validate_order_intent_capabilities
from .execution_journal import (
    DurableExecutionJournal,
    IntentLifecycle,
    SubmissionPreparation,
)
from .transport import (
    ExecutionTransport,
    SubmissionOutcomeUnknownError,
    TransportCancellation,
    TransportEventBatch,
    TransportOrderReference,
    TransportSubmission,
    TransportSubmitRequest,
    UnsupportedTransportCapabilityError,
    validate_transport_route,
)


@dataclass(frozen=True, slots=True)
class JournaledSubmissionOutcome:
    """Submission result plus the lifecycle reconstructed from durable facts."""

    preparation: SubmissionPreparation
    lifecycle: IntentLifecycle
    submitted: bool
    submission: TransportSubmission | None = None

    def __post_init__(self) -> None:
        if self.submitted != (self.submission is not None):
            raise ValueError("submitted must agree with presence of submission")
        if self.lifecycle.intent.intent_id != self.preparation.intent_id:
            raise ValueError("lifecycle and preparation must refer to the same intent")


class JournaledExecutionTransport:
    """The only new-path service allowed to turn a journal permit into submit.

    Approval, policy, preflight, and risk evaluation happen before an
    ``OrderIntent`` reaches this service.  This class only enforces transport
    capabilities, obtains the durable one-shot permit, invokes the transport,
    and journals normalized facts.
    """

    def __init__(
        self,
        transport: ExecutionTransport,
        journal: DurableExecutionJournal,
    ) -> None:
        self.transport = transport
        self.journal = journal

    def submit(
        self,
        intent: OrderIntent,
        *,
        idempotency_key: str,
        attempt_id: str,
        occurred_at: datetime | None = None,
    ) -> JournaledSubmissionOutcome:
        capabilities = self.transport.discover_capabilities()
        if not capabilities.supports_submit:
            raise UnsupportedTransportCapabilityError(
                f"{capabilities.backend_name} does not support submission"
            )
        validate_transport_route(intent, capabilities)
        validate_order_intent_capabilities(intent, capabilities.execution)

        preparation = self.journal.prepare_submission(
            intent,
            idempotency_key=idempotency_key,
            attempt_id=attempt_id,
            occurred_at=occurred_at,
        )
        if not preparation.should_submit:
            lifecycle = self.journal.replay().intents[intent.intent_id]
            return JournaledSubmissionOutcome(
                preparation=preparation,
                lifecycle=lifecycle,
                submitted=False,
            )

        request = TransportSubmitRequest(intent=intent, preparation=preparation)
        try:
            submission = self.transport.submit(request)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.journal.record_submission_uncertainty(
                intent.intent_id,
                attempt_id=preparation.attempt_id,
                reason=reason,
                occurred_at=occurred_at,
            )
            raise SubmissionOutcomeUnknownError(
                intent.intent_id,
                preparation.attempt_id,
                reason,
            ) from exc

        self.record_order_event(submission.order_event)
        for fill in submission.fills:
            self.record_fill(fill)
        lifecycle = self.journal.replay().intents[intent.intent_id]
        return JournaledSubmissionOutcome(
            preparation=preparation,
            lifecycle=lifecycle,
            submitted=True,
            submission=submission,
        )

    def record_order_event(self, event: OrderEvent) -> None:
        """Persist one normalized callback idempotently."""

        self.journal.append_order_event(event)

    def record_fill(self, fill: Fill) -> None:
        """Persist one normalized fill callback idempotently."""

        self.journal.append_fill(fill)

    def record_batch(self, batch: TransportEventBatch) -> IntentLifecycle:
        """Persist all query/poll facts and return the reconstructed lifecycle."""

        for event in batch.order_events:
            self.record_order_event(event)
        for fill in batch.fills:
            self.record_fill(fill)
        return self.journal.replay().intents[batch.reference.intent_id]

    def query_and_record(
        self,
        reference: TransportOrderReference,
    ) -> IntentLifecycle:
        """Query current broker facts and durably reconcile them."""

        return self.record_batch(self.transport.query(reference))

    def poll_and_record(
        self,
        reference: TransportOrderReference,
    ) -> IntentLifecycle:
        """Poll callbacks/fills and durably record the normalized facts."""

        return self.record_batch(self.transport.poll(reference))

    def cancel_and_record(
        self,
        reference: TransportOrderReference,
    ) -> TransportCancellation:
        """Request cancel and journal any immediately observable order event."""

        result = self.transport.cancel(reference)
        if result.order_event is not None:
            self.record_order_event(result.order_event)
        return result

    @staticmethod
    def reference_for_intent(intent: OrderIntent) -> TransportOrderReference:
        """Return the client-ID reference usable after a lost submit response."""

        return TransportOrderReference.from_intent(intent)

    def close(self) -> None:
        self.transport.close()


__all__ = ["JournaledExecutionTransport", "JournaledSubmissionOutcome"]
