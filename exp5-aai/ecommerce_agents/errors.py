"""Error hierarchy.

RecoverableError subclasses are retried (with a bounded retry budget).
PermanentError subclasses are never retried; they are reported to the Supervisor.
"""


class AgentSystemError(Exception):
    """Base class for all workflow errors."""


class RecoverableError(AgentSystemError):
    """Transient failure: safe to retry."""


class PermanentError(AgentSystemError):
    """Non-recoverable failure: do not retry."""


class TransientToolError(RecoverableError):
    """Tool temporarily unavailable."""


class ToolTimeoutError(RecoverableError):
    """Tool exceeded its execution timeout."""


class AgentExecutionError(RecoverableError):
    """Agent crashed during execution (transient)."""


class PermanentToolError(PermanentError):
    """Tool is permanently unavailable."""


class AccessDeniedError(PermanentError):
    """Agent attempted to use a tool it is not authorized for."""


class StateAccessError(PermanentError):
    """Agent attempted an unauthorized shared-state modification."""


class StateIntegrityError(PermanentError):
    """Shared state was modified outside the controlled write API."""


class InvalidInputError(PermanentError):
    """User or tool input failed validation."""


class ToolValidationError(PermanentError):
    """Tool call was malformed (unknown tool, bad arguments)."""


class ValidationFailedError(PermanentError):
    """Validator Agent rejected an intermediate or final result."""
