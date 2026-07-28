"""Recovery action methods for OrderLifecycleService (public facade).

The implementation is split into behavior-preserving submodules:

* ``_recovery_actions_single`` -- retry / cancel-remaining / resume-remaining /
  accept-partial + the shared ``_submit_child_attempt`` helper.
* ``_recovery_actions_reprice`` -- ``reprice_order`` (cancel + resubmit at new limit).
* ``_recovery_actions_stale`` -- ``retry_stale_orders`` (bulk stale retry).

External imports (``OrderLifecycleRecoveryActionsMixin``) resolve through this
shell so public behavior is unchanged. The abstract ``execute_orders`` /
``cancel_order`` placeholders (overridden by the concrete ``OrderLifecycleService``)
live on ``OrderLifecycleRecoverySingleMixin`` in ``_recovery_actions_single``.
"""

from ._recovery_actions_stale import OrderLifecycleRecoveryStaleMixin

__all__ = ["OrderLifecycleRecoveryActionsMixin"]


class OrderLifecycleRecoveryActionsMixin(OrderLifecycleRecoveryStaleMixin):
    """Recovery action methods for OrderLifecycleService."""
