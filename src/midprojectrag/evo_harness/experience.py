"""Versioned reviewed strategies. Episode notes never mutate this snapshot."""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json
import re

from .state import InvalidAction, exact, text


@dataclass(frozen=True)
class Experience:
    version: str = "empty-v1"
    entries: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        text(self.version, 128, "invalid_experience_version")
        if type(self.entries) is not tuple or len(self.entries) > 100:
            raise InvalidAction("invalid_experience_snapshot")
        for entry in self.entries:
            if type(entry) is not tuple or len(entry) != 2:
                raise InvalidAction("invalid_experience_entry")
            text(entry[0], 128, "invalid_strategy_id")
            text(entry[1], 500, "invalid_strategy")
        if len({entry[0] for entry in self.entries}) != len(self.entries):
            raise InvalidAction("duplicate_strategy_id")

    @property
    def fingerprint(self) -> str:
        return sha256(json.dumps([self.version, self.entries], ensure_ascii=False).encode()).hexdigest()

    @classmethod
    def from_reviewed(cls, payload: dict) -> Experience:
        exact(payload, {"version", "reviewed", "entries"})
        if payload["reviewed"] is not True or type(payload["entries"]) is not list:
            raise InvalidAction("reviewed_experience_required")
        values = []
        for row in payload["entries"]:
            exact(row, {"id", "strategy"})
            values.append((row["id"], row["strategy"]))
        return cls(payload["version"], tuple(values))

    def recall(self, query: str, limit: int) -> dict:
        terms = set(re.findall(r"\w+", query.casefold()))
        ranked = []
        for identifier, strategy in self.entries:
            hits = len(terms & set(re.findall(r"\w+", strategy.casefold())))
            if hits:
                ranked.append((-hits, identifier, strategy))
        ranked.sort()
        return {"version": self.version, "strategies": [
            {"id": identifier, "strategy": strategy} for _, identifier, strategy in ranked[:limit]],
            "trusted_instructions": False}
