class LLMUnreachableError(Exception):
    """No configured LLM provider could be reached for this call."""


class LLMTimeoutError(Exception):
    """A provider accepted the request but didn't respond within its timeout."""
