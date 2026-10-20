"""Проверка гипотез QD-Court: происхождение и подтверждённость (п. 5–6).

Гипотеза не получает положительный статус только за оценку модели —
здесь проверяются основания: источник существует в материалах, а числа
взяты из материалов. Иначе — UNSUPPORTED с причиной (остаётся в архиве).
"""

from __future__ import annotations

import re

from app.agents.evidence_pack import EvidencePack
from app.exploration.models import Hypothesis, HypothesisStatus

_NUM_RE = re.compile(r"\d+")


class HypothesisVerifier:
    def known_documents(self, pack: EvidencePack) -> set[str]:
        return {item.source_document for item in pack.items if item.source_document}

    def material_numbers(self, pack: EvidencePack) -> set[str]:
        found = set(pack.amounts)
        for item in pack.items:
            found |= set(item.amounts)
            found |= set(_NUM_RE.findall(item.text))
        return {value.lstrip("0") or "0" for value in found if value}

    def verify(self, hypothesis: Hypothesis, pack: EvidencePack) -> Hypothesis:
        known = self.known_documents(pack)
        numbers = self.material_numbers(pack)

        # Цифры в именах документов («05_protocol.txt» → «5») — не числа
        # дела: иначе мутация со ссылкой на источник отклонялась бы
        # сама собой.
        doc_digits = {
            value.lstrip("0") or "0"
            for source in known
            for value in _NUM_RE.findall(source)
        }

        sources_exist = all(source in known for source in hypothesis.sources)
        own_numbers = {
            value.lstrip("0") or "0"
            for value in _NUM_RE.findall(hypothesis.text)
        } - doc_digits
        numbers_ok = all(value in numbers for value in own_numbers)

        hypothesis.checks = {
            "sources_exist": sources_exist,
            "numbers_in_materials": numbers_ok,
        }
        if not sources_exist:
            hypothesis.status = HypothesisStatus.UNSUPPORTED
            hypothesis.rejection_reason = (
                "источник не найден в материалах дела: "
                + ", ".join(
                    source
                    for source in hypothesis.sources
                    if source not in known
                )
            )
        elif not numbers_ok:
            hypothesis.status = HypothesisStatus.UNSUPPORTED
            hypothesis.rejection_reason = (
                "число в гипотезе не подтверждено материалами: "
                + ", ".join(sorted(own_numbers - numbers)[:5])
            )
        else:
            # SUPPORTED — «основания подтверждены», не «факт доказан».
            hypothesis.status = HypothesisStatus.SUPPORTED
        return hypothesis
