"""Domain models shared across collectors, storage, and the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field

from .urls import domain_of


@dataclass
class Candidate:
    """A discovered service candidate before verification."""
    url: str
    name: str = ""
    description: str = ""
    source_platform: str = ""
    upvotes: int = 0
    domain: str = field(default="")

    def __post_init__(self):
        if not self.domain:
            self.domain = domain_of(self.url)
