"""QD-Court: экспериментальный поиск направлений анализа (Этапы 4–5 ТЗ).

Идеи взяты из QD-Rec (SakanaAI, Apache-2.0): архив гипотез, novelty-first
admission, локальная конкуренция, сохранение отклонённых. Механизм
рекомендаций НЕ копируется: вместо LLM-предлагающего и судьи — правила
проекта, а архив живёт в JSON по одному файлу на дело.

Границы (неизменяемые):
* модуль не меняет исход дела, суммы и детерминированные части акта
  (`RULES_BUILT_SECTIONS`) — он вообще не получает проект на вход;
* гипотеза никогда не становится «доказанным фактом»: статус SUPPORTED
  означает только «источники и числа подтверждены», человек решает сам;
* архив изолирован по делам, гипотезы чужих дел не используются;
* отказ модели/источника/архива — безопасный возврат к конвейеру.
"""

from app.exploration.archive import ExplorationArchive, admit
from app.exploration.models import HumanReviewStatus, Hypothesis, HypothesisStatus
from app.exploration.proposer import DirectionProposer
from app.exploration.service import (
    ExplorationBudget,
    ExplorationReport,
    ExplorationService,
)
from app.exploration.verification import HypothesisVerifier

__all__ = [
    "ExplorationArchive",
    "ExplorationBudget",
    "ExplorationReport",
    "ExplorationService",
    "Hypothesis",
    "HypothesisStatus",
    "HumanReviewStatus",
    "DirectionProposer",
    "HypothesisVerifier",
    "admit",
]
