"""Assessment-specific domain errors — subclass the shared_kernel hierarchy
(Domain Model §1's rule: contexts express errors in terms of the shared
vocabulary, not invent parallel exception trees). Deliberately NOT shared
with Identity's own error subclasses of the same shape (e.g.
``OptimisticConcurrencyError``) — each context's error hierarchy is
self-contained around the shared base classes, consistent with Sprint 1's
established pattern.
"""

from __future__ import annotations

from georisk.shared_kernel.errors import (
    ConcurrencyConflictError,
    GuardRejectedError,
    IllegalStateTransitionError,
    NotFoundError,
    ValidationFailedError,
)


class AssessmentNotFoundError(NotFoundError):
    pass


class IllegalAssessmentStatusTransitionError(IllegalStateTransitionError):
    pass


class OptimisticConcurrencyError(ConcurrencyConflictError):
    pass


# --- Workflow Engine (Roadmap Sprint 3) ------------------------------------


class WorkflowTemplateNotFoundError(NotFoundError):
    pass


class CyclicWorkflowTemplateError(ValidationFailedError):
    """A ``WorkflowTemplate``'s stage-definition graph cannot be
    topologically sorted — construction-time invariant, never persisted.
    """


class UnknownStagePredecessorError(ValidationFailedError):
    """A ``StageDefinition`` names a predecessor stage type that isn't
    itself defined anywhere in the same template.
    """


class IllegalWorkflowTemplateStatusTransitionError(IllegalStateTransitionError):
    pass


class IllegalStageExecutionTransitionError(IllegalStateTransitionError):
    """A stage's ``StageProgressEntry`` was asked to move to a status not
    legal from its current one (Domain Model §6's FSM pattern, applied to
    the per-stage mini state machine).
    """


class WorkflowNotCompleteError(GuardRejectedError):
    """``AdvanceAssessmentCommand`` was issued before every required stage
    reached COMPLETE.
    """
