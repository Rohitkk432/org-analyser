"""Collector contract: take the dataset's repos, return column values."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..discovery import Repo


class Collector(ABC):
    """A unit of measurement that produces one or more sheet columns.

    Collectors are independent and run concurrently. A collector must not raise for
    expected gaps (missing tool, no git history, no remote); it returns whatever it can
    and pushes a human-readable note onto ``warnings``.
    """

    #: Stable name for logging.
    name: str = "collector"

    def __init__(self, repos: list[Repo]) -> None:
        self.repos = repos
        self.warnings: list[str] = []

    @abstractmethod
    def collect(self) -> dict[str, object]:
        """Return ``{internal_key: value}`` for the columns this collector owns."""

    def warn(self, message: str) -> None:
        self.warnings.append(f"[{self.name}] {message}")
