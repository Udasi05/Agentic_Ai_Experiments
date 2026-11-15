"""Custom exceptions."""


class WorkflowError(Exception):
    """Fatal workflow problem (missing file, bad header, invalid rules). Stops scoring."""


class DeliveryError(Exception):
    """A (simulated) notification delivery attempt failed."""
