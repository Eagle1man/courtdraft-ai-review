"""Модели QD-Court (Этап 4 ТЗ, п. «Контракт гипотезы»)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import cast


class HypothesisStatus(StrEnum):
    """Жизненный цикл гипотезы.

    SUPPORTED — не «доказана», а «источники и числа подтверждены
    материалами». Оценку по существу даёт человек.
    """

    PROPOSED = "PROPOSED"
    SUPPORTED = "SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class HumanReviewStatus(StrEnum):
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    NOT_REQUIRED = "NOT_REQUIRED"


@dataclass
class Hypothesis:
    """Одно направление анализа, найденное поиском.

    Обязательные поля контракта: дело, вопрос, тип, текст, источники,
    родители (для мутаций), версия модели/промпта, новизна, проверки,
    причины отклонения, статус проверки человеком, история изменений
    (created_at + updated_at).
    """

    id: str
    case_id: str
    question_id: str
    kind: str
    text: str
    sources: list[str] = field(default_factory=list)
    parent_ids: list[str] = field(default_factory=list)
    model_version: str = "rules-1"
    novelty: float = 0.0
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    rejection_reason: str = ""
    human_review: HumanReviewStatus = HumanReviewStatus.PENDING
    checks: dict[str, bool] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now().isoformat(timespec="seconds")
    )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Hypothesis:
        return cls(
            id=str(data["id"]),
            case_id=str(data["case_id"]),
            question_id=str(data["question_id"]),
            kind=str(data["kind"]),
            text=str(data["text"]),
            sources=cast("list[str]", data.get("sources", [])),
            parent_ids=cast("list[str]", data.get("parent_ids", [])),
            model_version=str(data.get("model_version", "rules-1")),
            novelty=float(str(data.get("novelty", 0.0))),
            status=HypothesisStatus(str(data.get("status", "PROPOSED"))),
            rejection_reason=str(data.get("rejection_reason", "")),
            human_review=HumanReviewStatus(str(data.get("human_review", "PENDING"))),
            checks=cast("dict[str, bool]", data.get("checks", {})),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
        )
