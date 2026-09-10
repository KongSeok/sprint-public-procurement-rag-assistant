from __future__ import annotations


class CatalogError(ValueError):
    """Fail-closed catalog error with a stable, non-sensitive machine code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)
