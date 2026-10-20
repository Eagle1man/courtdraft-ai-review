"""Предлагающий QD-Court: Explore и Mutate (Этап 5 ТЗ).

Первая версия — на правилах проекта, без модели: Ollama в окружении
недоступен, а ТЗ разрешает начинать с минимального варианта. Точка
расширения одна: `DirectionProposer` при появлении локальной модели
может генерировать формулировки сам, контракт гипотезы не меняется.

Направления берутся из того, что конвейер уже умеет считать по материалам:
непокрытые обстоятельства, доводы сторон, противоречия сумм, нормы из
материалов, вопросы квалификации. Ничего не выдумывается: текст
направления строится из фрагментов материалов.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.agents.evidence_pack import EvidencePack
from app.exploration.archive import new_id
from app.exploration.models import Hypothesis
from app.verification.engine import SYSTEM_LAWS
from app.verification.qualification import check_qualification

_LAW_RE = re.compile(r"ст\.\s*(\d+(?:\.\d+)?)\s+([А-ЯЁ]{2,})", re.IGNORECASE)

#: Шаблонные фразы в отзывах: отсылка к ст. 56 ГПК, «возражений не
#: поступило». Направлением анализа они не являются — это не довод,
#: а констатация процессуального факта.
_BOILERPLATE_RE = re.compile(
    r"ст\.?\s*56\s*ГПК"
    r"|возражени\w*\s+(?:относительно|не\s+поступило|не\s+представлено)"
    r"|ходатайств\w*\s+(?:и\s+возражений\s+)?(?:не\s+поступило|не\s+заявлено)",
    re.IGNORECASE,
)


@dataclass
class DirectionProposer:
    model_version: str = "rules-1"
    max_directions: int = 8

    def explore(self, pack: EvidencePack) -> list[Hypothesis]:
        """Найти направления анализа, которые конвейер не проверяет."""
        found: list[Hypothesis] = []

        # 1. Доводы сторон: каждый фрагмент возражений — возможное
        #    пропущенное направление.
        for item in pack.items:
            if item.category != "objections":
                continue
            if _BOILERPLATE_RE.search(item.text):
                continue
            found.append(
                Hypothesis(
                    id=new_id(),
                    case_id="",
                    question_id=f"objection:{item.source_document}:{item.order}",
                    kind="objection_coverage",
                    text=(
                        "направление: разобрать довод стороны «"
                        f"{item.text[:120]}»"
                    ),
                    sources=[item.source_document],
                    model_version=self.model_version,
                )
            )

        # 2. Противоречие сумм в требованиях: разные суммы по одному
        #    основанию — вопрос, какая просительная.
        claims = pack.by_category("claims")
        sums = {
            amount
            for item in claims
            for amount in item.amounts
            if amount
        }
        if len(sums) > 1:
            docs = sorted({item.source_document for item in claims if item.amounts})
            found.append(
                Hypothesis(
                    id=new_id(),
                    case_id="",
                    question_id="claims:amounts",
                    kind="contradiction_amounts",
                    text=(
                        "направление: в требованиях разные суммы "
                        f"({', '.join(sorted(sums)[:5])}) — проверить, какая "
                        "сумма просительная"
                    ),
                    sources=docs[:4],
                    model_version=self.model_version,
                )
            )

        # 3. Нормы из материалов, которых нет среди системных: их
        #    применение суд решает сам, но направление стоит проверить.
        material_laws: set[tuple[str, str]] = set()
        for item in pack.items:
            for match in _LAW_RE.finditer(item.text):
                material_laws.add((match.group(1), match.group(2).upper()))
        system = {tuple(law) for law in SYSTEM_LAWS}
        extra = sorted(material_laws - system)[:3]
        for number, code in extra:
            found.append(
                Hypothesis(
                    id=new_id(),
                    case_id="",
                    question_id=f"law:{number}:{code}",
                    kind="norm_from_materials",
                    text=(
                        "направление: в материалах ссылка на ст. "
                        f"{number} {code} — проверить, применима ли норма и "
                        "в какой редакции"
                    ),
                    sources=[],
                    model_version=self.model_version,
                )
            )

        # 4. Вопросы квалификации (та же логика, что в проверке, —
        #    но здесь это направление для поиска, а не замечание).
        plaintiff = _side(pack, "истец")
        defendant = _side(pack, "ответчик")
        texts = [item.text for item in pack.items]
        for finding in check_qualification(texts, plaintiff, defendant):
            found.append(
                Hypothesis(
                    id=new_id(),
                    case_id="",
                    question_id=f"qualification:{finding.kind}",
                    kind=finding.kind,
                    text=f"направление: {finding.reason}",
                    sources=[],
                    model_version=self.model_version,
                )
            )

        return found[: self.max_directions]

    def mutate(self, pack: EvidencePack, parent: Hypothesis) -> Hypothesis | None:
        """Уточнить гипотезу новым фрагментом из её же источника."""
        for item in pack.items:
            if item.source_document not in parent.sources:
                continue
            if item.text[:60] in parent.text:
                continue
            child = Hypothesis(
                id=new_id(),
                case_id=parent.case_id,
                question_id=parent.question_id,
                kind=parent.kind,
                text=(
                    f"{parent.text} Уточнение из {item.source_document}: "
                    f"«{item.text[:100]}»"
                ),
                sources=sorted(set(parent.sources + [item.source_document])),
                parent_ids=[parent.id],
                model_version=self.model_version,
            )
            return child
        return None


def _side(pack: EvidencePack, role: str) -> str:
    marker = f" ({role})"
    for entry in pack.participants:
        if entry.endswith(marker):
            return entry[: -len(marker)]
    return ""
