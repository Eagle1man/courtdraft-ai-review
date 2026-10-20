"""Архив гипотез: один JSON на дело, изоляция, локальная конкуренция.

Отклонённые гипотезы сохраняются для аудита с причиной отказа (п. 3
правил архива ТЗ). Гипотезы чужих дел не читаются и не влияют на отбор.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from app.exploration.models import Hypothesis, HypothesisStatus

#: Новизна ниже порога — повтор, а не новое направление.
DEFAULT_NOVELTY_THRESHOLD = 0.5


class ExplorationArchive:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, case_id: str) -> Path:
        safe = case_id.replace("/", "_").replace("\\", "_")
        return self.root / f"{safe}.json"

    def load(self, case_id: str) -> list[Hypothesis]:
        """Гипотезы ТОЛЬКО этого дела (изоляция по файлу)."""
        path = self._path(case_id)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [Hypothesis.from_dict(item) for item in data.get("hypotheses", [])]

    def save(self, case_id: str, hypotheses: list[Hypothesis]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        kept = [h for h in hypotheses if h.case_id == case_id]
        payload = {
            "case_id": case_id,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "hypotheses": [h.to_dict() for h in kept],
        }
        self._path(case_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def add(self, case_id: str, hypothesis: Hypothesis) -> list[Hypothesis]:
        """Дописать гипотезу в архив дела и сохранить."""
        hypotheses = self.load(case_id)
        hypotheses.append(hypothesis)
        self.save(case_id, hypotheses)
        return hypotheses


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def admit(
    hypotheses: list[Hypothesis],
    candidate: Hypothesis,
    threshold: float = DEFAULT_NOVELTY_THRESHOLD,
) -> list[Hypothesis]:
    """Novelty-first admission + локальная конкуренция.

    Повтор (новизна ниже порога) остаётся в архиве со статусом REJECTED
    и причиной. В пределах одного вопроса (`question_id`) живёт самая
    новизнная версия: предыдущая получает SUPERSEDED и причину вытеснения.
    """
    now = datetime.now().isoformat(timespec="seconds")
    result = list(hypotheses)

    # Повторный прогон не должен раздувать архив: идентичный отказ
    # (тот же вопрос и тот же текст) уже лежит в архиве — не дублируем.
    if any(
        h.question_id == candidate.question_id and h.text == candidate.text
        for h in result
    ):
        return result

    if candidate.novelty < threshold:
        candidate.status = HypothesisStatus.REJECTED
        candidate.rejection_reason = (
            f"новизна {candidate.novelty} ниже порога {threshold} — повтор"
        )
        candidate.updated_at = now
        result.append(candidate)
        return result

    rival = next(
        (h for h in result if h.question_id == candidate.question_id), None
    )
    if rival is not None and rival.novelty >= candidate.novelty:
        candidate.status = HypothesisStatus.REJECTED
        candidate.rejection_reason = (
            f"по вопросу {candidate.question_id} уже есть версия "
            f"новизны {rival.novelty}"
        )
        candidate.updated_at = now
        result.append(candidate)
        return result

    if rival is not None:
        rival.status = HypothesisStatus.SUPERSEDED
        rival.rejection_reason = (
            f"вытеснена версией {candidate.id} новизны {candidate.novelty}"
        )
        rival.updated_at = now
    result.append(candidate)
    return result
