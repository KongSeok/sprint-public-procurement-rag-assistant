from __future__ import annotations

import fcntl
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator, Protocol

from midprojectrag.ingest.common import sha256_text


MONEY_QUANTUM = Decimal("0.000000001")


def _decimal(value: Decimal | float | int | str, error_code: str) -> Decimal:
    try:
        parsed = Decimal(str(value)).quantize(MONEY_QUANTUM)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(error_code) from error
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(error_code)
    return parsed


@dataclass(frozen=True)
class BudgetSnapshot:
    limit_usd: Decimal
    committed_usd: Decimal
    reserved_usd: Decimal
    available_usd: Decimal
    breached: bool


class Budget(Protocol):
    """Provider-neutral reservation port used by shared orchestration."""

    def reserve(
        self,
        estimated_usd: Decimal | float | int | str,
        operation_id: str,
    ) -> str: ...

    def commit(
        self,
        reservation_id: str,
        actual_usd: Decimal | float | int | str,
    ) -> None: ...

    def release(self, reservation_id: str) -> None: ...


class BudgetLedger:
    """A small process-safe USD ledger that rejects calls before overspend."""

    def __init__(self, path: Path, limit_usd: Decimal | float | int | str = 20) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.limit_usd = _decimal(limit_usd, "invalid_budget_limit")
        if self.limit_usd <= 0:
            raise ValueError("invalid_budget_limit")

    def _new_state(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "limit_usd": str(self.limit_usd),
            "committed_usd": str(Decimal("0").quantize(MONEY_QUANTUM)),
            "breached": False,
            "estimation_misses": 0,
            "reservations": {},
        }

    def _read_state(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._new_state()
        with self.path.open("r", encoding="utf-8") as source:
            state = json.load(source)
        if not isinstance(state, dict) or state.get("schema_version") != "1.0":
            raise ValueError("invalid_budget_ledger")
        stored_limit = _decimal(state.get("limit_usd"), "invalid_budget_ledger")
        if stored_limit != self.limit_usd:
            raise ValueError("budget_limit_mismatch")
        _decimal(state.get("committed_usd"), "invalid_budget_ledger")
        reservations = state.get("reservations")
        if not isinstance(reservations, dict):
            raise ValueError("invalid_budget_ledger")
        for reservation in reservations.values():
            if not isinstance(reservation, dict):
                raise ValueError("invalid_budget_ledger")
            _decimal(reservation.get("reserved_usd"), "invalid_budget_ledger")
        if not isinstance(state.get("breached"), bool):
            raise ValueError("invalid_budget_ledger")
        estimation_misses = state.get("estimation_misses", 0)
        if not isinstance(estimation_misses, int) or isinstance(estimation_misses, bool) or estimation_misses < 0:
            raise ValueError("invalid_budget_ledger")
        state["estimation_misses"] = estimation_misses
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(state, output, ensure_ascii=False, indent=2, sort_keys=True)
                output.write("\n")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = self._read_state()
            yield state
            self._write_state(state)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _reserved_total(state: dict[str, Any]) -> Decimal:
        return sum(
            (_decimal(item["reserved_usd"], "invalid_budget_ledger") for item in state["reservations"].values()),
            Decimal("0"),
        ).quantize(MONEY_QUANTUM)

    def reserve(self, estimated_usd: Decimal | float | int | str, operation_id: str) -> str:
        amount = _decimal(estimated_usd, "invalid_budget_reservation")
        if amount <= 0:
            raise ValueError("invalid_budget_reservation")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("invalid_budget_operation")
        reservation_id = uuid.uuid4().hex
        with self._locked_state() as state:
            if state["breached"]:
                raise ValueError("budget_already_breached")
            committed = _decimal(state["committed_usd"], "invalid_budget_ledger")
            if committed + self._reserved_total(state) + amount > self.limit_usd:
                raise ValueError("budget_limit_exceeded")
            state["reservations"][reservation_id] = {
                "operation_sha256": sha256_text(operation_id),
                "reserved_usd": str(amount),
            }
        return reservation_id

    def commit(self, reservation_id: str, actual_usd: Decimal | float | int | str) -> None:
        actual = _decimal(actual_usd, "invalid_actual_cost")
        breached = False
        with self._locked_state() as state:
            reservation = state["reservations"].pop(reservation_id, None)
            if reservation is None:
                raise ValueError("budget_reservation_missing")
            reserved = _decimal(reservation["reserved_usd"], "invalid_budget_ledger")
            committed = _decimal(state["committed_usd"], "invalid_budget_ledger")
            new_committed = (committed + actual).quantize(MONEY_QUANTUM)
            if actual > reserved:
                state["estimation_misses"] += 1
            breached = new_committed + self._reserved_total(state) > self.limit_usd
            state["committed_usd"] = str(new_committed)
            state["breached"] = bool(state["breached"] or breached)
        if breached:
            raise ValueError("budget_reservation_exceeded")

    def release(self, reservation_id: str) -> None:
        with self._locked_state() as state:
            if state["reservations"].pop(reservation_id, None) is None:
                raise ValueError("budget_reservation_missing")

    def snapshot(self) -> BudgetSnapshot:
        with self._locked_state() as state:
            committed = _decimal(state["committed_usd"], "invalid_budget_ledger")
            reserved = self._reserved_total(state)
            available = max(Decimal("0"), self.limit_usd - committed - reserved)
            return BudgetSnapshot(
                limit_usd=self.limit_usd,
                committed_usd=committed,
                reserved_usd=reserved,
                available_usd=available.quantize(MONEY_QUANTUM),
                breached=state["breached"],
            )
