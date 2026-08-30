"""Evidence timeline: every claim CodeProof makes is backed by a logged,
timestamped piece of evidence (a command + its actual output), never by an
LLM's unverified assertion."""
from __future__ import annotations

import dataclasses
import time
from typing import Any


@dataclasses.dataclass
class EvidenceEntry:
    timestamp: float
    claim: str
    evidence: str
    passed: bool | None
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)


class EvidenceTimeline:
    def __init__(self) -> None:
        self.entries: list[EvidenceEntry] = []

    def record(self, claim: str, evidence: str, passed: bool | None = None, **metadata: Any) -> None:
        self.entries.append(EvidenceEntry(
            timestamp=time.time(), claim=claim, evidence=evidence, passed=passed, metadata=metadata,
        ))

    def to_list(self) -> list[dict[str, Any]]:
        return [dataclasses.asdict(e) for e in self.entries]
