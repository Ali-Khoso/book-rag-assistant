"""Safe processing failures that can be shown in the user's library."""


class ProcessingError(Exception):
    """Explain a recoverable document failure without exposing credentials or text."""


class LostLease(Exception):
    """Stop a task when its document was deleted or another run claimed it."""
