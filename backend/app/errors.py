class UnsupportedDocumentError(Exception):
    """Raised when a document cannot be processed. `reason` is a stable machine-readable code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class OverviewGenerationError(Exception):
    """Raised when a structured overview cannot be generated. `reason` is a
    stable machine-readable code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class QuizGenerationError(Exception):
    """Raised when a multiple-choice quiz cannot be generated. `reason` is a
    stable machine-readable code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class PresentationGenerationError(Exception):
    """Raised when a slide deck cannot be generated. `reason` is a stable
    machine-readable code."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


class InterviewError(Exception):
    """Raised when a mock interview turn cannot be produced. `reason` is a
    stable machine-readable code, same convention as the generation errors
    above - but unlike those, the interview is synchronous, so this surfaces
    as an HTTP error on the request rather than a FAILED status on a row."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)
