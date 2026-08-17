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
