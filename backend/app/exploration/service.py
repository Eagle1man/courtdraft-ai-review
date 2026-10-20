"""Сервис QD-Court: прогон поиска с бюджетом и безопасным возвратом.

Модуль НЕ получает проект судебного акта и не может изменить исход,
суммы или детерминированные части (`RULES_BUILT_SECTIONS`): на входе
только пакет материалов дела. Любая ошибка (нет модели, испорченный
архив, пустой пакет) — возврат к обычному конвейеру: пустой список
гипотез и признак fallback в отчёте.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.agents.evidence_pack import EvidencePack
from app.exploration.archive import ExplorationArchive, admit
from app.exploration.models import Hypothesis
from app.exploration.novelty import novelty
from app.exploration.proposer import DirectionProposer
from app.exploration.verification import HypothesisVerifier


@dataclass
class ExplorationBudget:
    """Ограничения прогона: итерации, время, размер архива, порог новизны."""

    max_iterations: int = 20
    max_seconds: float = 30.0
    max_hypotheses: int = 10
    novelty_threshold: float = 0.5


@dataclass
class ExplorationReport:
    case_id: str
    hypotheses: list[Hypothesis] = field(default_factory=list)
    iterations: int = 0
    fallback: bool = False
    reason: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    @property
    def active(self) -> list[Hypothesis]:
        return [
            h
            for h in self.hypotheses
            if h.status.value in {"PROPOSED", "SUPPORTED"}
        ]

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "iterations": self.iterations,
            "fallback": self.fallback,
            "reason": self.reason,
            "created_at": self.created_at,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
        }


class ExplorationService:
    def __init__(
        self,
        archive_root: Path,
        budget: ExplorationBudget | None = None,
    ) -> None:
        self.archive = ExplorationArchive(archive_root)
        self.proposer = DirectionProposer()
        self.verifier = HypothesisVerifier()
        self.budget = budget or ExplorationBudget()

    def run(self, case_id: str, pack: EvidencePack) -> ExplorationReport:
        try:
            return self._run(case_id, pack)
        except Exception as exc:  # noqa: BLE001
            # Безопасный возврат: конвейер работает без поиска.
            return ExplorationReport(
                case_id=case_id,
                fallback=True,
                reason=f"{type(exc).__name__}: {exc}",
            )

    def _run(self, case_id: str, pack: EvidencePack) -> ExplorationReport:
        hypotheses = self.archive.load(case_id)
        candidates = self.proposer.explore(pack)
        deadline = time.monotonic() + self.budget.max_seconds
        iterations = 0
        active = 0

        for candidate in candidates:
            if (
                iterations >= self.budget.max_iterations
                or time.monotonic() > deadline
                or active >= self.budget.max_hypotheses
            ):
                break
            iterations += 1
            candidate.case_id = case_id
            candidate.novelty = novelty(
                candidate.text, [h.text for h in hypotheses]
            )
            candidate = self.verifier.verify(candidate, pack)
            if candidate.status.value == "SUPPORTED":
                active += 1
            hypotheses = admit(
                hypotheses, candidate, self.budget.novelty_threshold
            )

        # Мутации: уточняем подтверждённые гипотезы фрагментами их
        # источников, пока есть бюджет.
        parents = [h for h in hypotheses if h.status.value == "SUPPORTED"]
        for parent in parents:
            if iterations >= self.budget.max_iterations or time.monotonic() > deadline:
                break
            child = self.proposer.mutate(pack, parent)
            if child is None:
                continue
            iterations += 1
            child.novelty = novelty(child.text, [h.text for h in hypotheses])
            child = self.verifier.verify(child, pack)
            hypotheses = admit(hypotheses, child, self.budget.novelty_threshold)

        self.archive.save(case_id, hypotheses)
        return ExplorationReport(
            case_id=case_id,
            hypotheses=hypotheses,
            iterations=iterations,
        )
