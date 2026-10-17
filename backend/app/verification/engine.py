"""Verification Engine (Фаза 10, ТЗ п.28, п.29).

Проверяет сгенерированный проект на соответствие материалам дела.

Ключевая идея: проверка НЕ доверяет модели. Модель в 1.5B на CPU
выдумывает суммы и факты чаще, чем пишет хорошо, поэтому все числа
сверяются с пакетом доказательств регулярками, а не словами модели
о том, что «всё соответствует материалам».

Проверки:
- числа в тексте, которых нет в материалах (главный источник ошибок);
- ссылки на нормы права без соответствующего блока в материалах;
- разделы, помеченные моделью как требующие проверки;
- разделы, для которых в материалах нет данных вообще;
- разделы без единой ссылки на источник.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.agents.draft_agent import NEEDS_REVIEW, DraftResult
from app.agents.evidence_pack import EvidencePack
from app.drafting.operative import DEFAULT_LEGAL_BASIS
from app.verification.persons import check_section


class VerificationStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - статус проверки, не пароль
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


class IssueType(StrEnum):
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    MISSING_SOURCE = "MISSING_SOURCE"
    INCORRECT_QUOTE = "INCORRECT_QUOTE"
    LAW_NOT_FOUND = "LAW_NOT_FOUND"
    PRACTICE_NOT_FOUND = "PRACTICE_NOT_FOUND"
    CONTRADICTION = "CONTRADICTION"
    INCOMPLETE = "INCOMPLETE"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class Issue:
    """Замечание по проверке."""

    type: IssueType
    severity: Severity
    text: str
    reason: str
    section: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "text": self.text[:300],
            "reason": self.reason,
            "section": self.section,
        }


@dataclass
class VerificationReport:
    """Результат проверки проекта."""

    status: VerificationStatus = VerificationStatus.PASS
    issues: list[Issue] = field(default_factory=list)
    sections_checked: int = 0
    claims_checked: int = 0
    unsupported_claims: int = 0

    @property
    def needs_review(self) -> bool:
        return self.status is not VerificationStatus.PASS

    def by_severity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.severity.value] = counts.get(issue.severity.value, 0) + 1
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "issues": [issue.to_dict() for issue in self.issues],
            "sections_checked": self.sections_checked,
            "claims_checked": self.claims_checked,
            "unsupported_claims": self.unsupported_claims,
            "by_severity": self.by_severity(),
        }

    def human_summary(self) -> str:
        if not self.issues:
            return "Замечаний нет: все разделы опираются на материалы дела."

        lines = [f"Статус проверки: {self.status.value}", ""]
        for issue in self.issues:
            lines.append(
                f"[{issue.severity.value}] {issue.section or 'проект целиком'}\n"
                f"  {issue.type.value}: {issue.reason}\n"
                f"  фрагмент: {issue.text[:140]}"
            )
        counts = self.by_severity()
        lines.append("")
        lines.append(
            "Итого: " + ", ".join(f"{k} — {v}" for k, v in sorted(counts.items()))
        )
        return "\n".join(lines)


# Числа, которые встречаются в тексте проекта.
_NUM_RE = re.compile(r"\b(\d[\d\s ]{1,12})\b")
# Ссылки на нормы. Учитываются падежные формы: «статья 310», «статьи 310»,
# «статье 310», «статью 310», «ст. 310», «п. 1 ст. 486». Без «статье»
# ссылка не распознавалась вовсе, и выдуманная норма проходила проверку.
_LAW_RE = re.compile(
    # «ст.» и «статья N» имеют приоритет над «п. N»: иначе «п. 1 ст. 486»
    # распознаётся как «пункт 1 статьи СТ», то есть как выдуманная норма.
    #
    # Падежные формы перечислены полностью, включая «статьей»: без неё
    # ссылка не распознавалась, а её номер статьи тут же попадал в
    # проверку чисел и помечался как выдуманная сумма — то есть
    # корректная ссылка на норму давала ложную тревогу CRITICAL.
    r"(?:ст\.|стат(?:ьёй|ьей|ье|ьи|ью|ьями|ьях|ьям|ьё|и)\.?)\s*"
    r"(\d+(?:\s*(?:,|и)\s*\d+)*)"
    r"\s*(?:([А-ЯЁ][А-ЯЁ ]{0,12}?)(?:РФ|кодекс))?",
    re.IGNORECASE,
)


def _numbers_in(text: str) -> set[str]:
    """Числа в тексте, пригодные для сверки с материалами.

    Пропускаются реквизиты: ИНН, ОГРН, номера счетов — длинные
    последовательности с ведущими нулями («000000000000», «002»).
    Это не суммы, и проверка не должна кричать «выдуманное число»
    на каждый ИНН в тексте.
    """
    out: set[str] = set()
    for raw in _NUM_RE.findall(text):
        digits = re.sub(r"[^\d]", "", raw)
        if len(digits) < 2:
            continue
        # Ведущие нули — признак реквизита, а не суммы.
        if len(digits) > 1 and digits[0] == "0":
            continue
        if set(digits) == {"0"}:
            continue
        out.add(digits)
    return out


def _laws_in(text: str) -> set[tuple[str, str]]:
    """Найти ссылки на нормы в виде (статья, кодекс).

    Кодекс определяется по ближайшему упоминанию после номера статьи.
    Если кодекс не указан прямо, ищем в окне контекста — иначе ссылка
    «статья 310» останется без кодекса и не с чем сравнивать.
    """
    known = ("ГПК", "ГК", "УК", "АПК", "ТК", "СК", "КАС", "КоАП")
    found: set[tuple[str, str]] = set()

    for m in _LAW_RE.finditer(text):
        # «статьями 309, 310, 314 ГК РФ» — это три ссылки, а не одна.
        # «статьями 309, 310 и 314 ГК РФ» — это три ссылки, а не одна.
        # Список разделяется и запятой, и союзом «и»: модель пишет и так,
        # и так, а приведённая форма без разбора давала «310 и 314» одним
        # номером статьи, и обе ссылки уходили в проверку чисел.
        articles = [
            a.strip()
            for a in re.split(r"\s*(?:,|и)\s*", m.group(1))
            if a.strip()
        ]
        code = (m.group(2) or "").strip().upper()

        if not code:
            tail = text[m.end() : m.end() + 40].upper()
            for name in known:
                if name in tail:
                    code = name
                    break

        for article in articles:
            # Без кодекса ссылку невозможно подтвердить: она всегда будет
            # отмечена как неподтверждённая. Это правильное поведение —
            # безопаснее перестраховаться, чем пропустить выдуманную норму.
            found.add((article, code or ""))

    return found


def _is_sum_of(digits: str, backed: set[int]) -> bool:
    """Сумма ли это из двух-трёх чисел, уже подтверждённых материалами.

    Проверяется только сумма двух и трёх слагаемых: этого хватает для
    строки «а всего» и для процентов по ключевой ставке, а перебор всех
    подмножеств при большом числе сумм дал бы неверные совпадения.

    Числа в тексте собраны без ведущих нулей, поэтому и сравнение идёт
    по целым значениям, а не по строкам.
    """
    try:
        target = int(digits)
    except ValueError:
        return False

    values = sorted(backed)
    for index, first in enumerate(values):
        if first == target:
            # Сумма из одного слагаемого — это не сумма: такое число
            # должно быть подтверждено материалами напрямую.
            return False
        for second in values[index + 1 :]:
            if first + second == target:
                return True
            for third in values[index + 2 :]:
                if first + second + third == target:
                    return True
    return False


#: Нормы, которые система приводит сама по закону.
#:
#: Смысл в том, что подтверждать их материалами дела бессмысленно:
#: в исковом заявлении судья ст. 198 ГПК не упоминает, она появляется
#: в самом акте суда. До появления этого списка проверка объявляла
#: нормативную часть собственной резолюции неподтверждённой — три
#: замечания HIGH на проекте, собранном по правилам.
SYSTEM_LAWS: frozenset[tuple[str, str]] = frozenset(
    {
        ("198", "ГПК"),  # основание принятия решения
        ("98", "ГПК"),  # распределение судебных расходов, пошлина в бюджет
        ("100", "ГПК"),  # расходы на представителя
        ("233", "ГПК"),  # заочное решение
        ("321", "ГПК"),  # срок подачи апелляционной жалобы
    }
)


def verify_draft(draft: DraftResult, pack: EvidencePack) -> VerificationReport:
    """Проверить проект на соответствие материалам дела."""
    report = VerificationReport(sections_checked=len(draft.sections))

    # Числа и нормы, реально присутствующие в материалах.
    material_numbers: set[str] = set(pack.amounts)
    material_laws: set[tuple[str, str]] = set()
    for item in pack.items:
        material_numbers |= set(item.amounts)
        material_laws |= _laws_in(item.text)

    # Допускаем номера статей и даты из дат дела: они не суммы, но
    # встречаются в материалах и их отсутствие в пакете — ложное срабатывание.
    for date_value in pack.dates:
        material_numbers |= _numbers_in(date_value)
    material_numbers |= {re.sub(r"\D", "", p) for p in [pack.case_number]}
    material_numbers.discard("")
    # Номера частей и пунктов встречаются почти везде.
    small_numbers = {str(i) for i in range(1, 50)}

    # Нормы, которые система цитирует сама, по закону, а не берёт из
    # материалов дела. Разбор 1 425 гражданских решений: ст. 198 ГПК —
    # основание принятия решения, 521 документ; «в доход бюджета» — 98
    # документов (6,9 %), ст. 233 — 87 (заочное решение), ст. 321 — 87
    # (срок обжалования). Ни одну из них сторона в иске не пишет, поэтому
    # требовать подтверждения материалами нельзя: система ругалась сама
    # на собственную резолютивную часть.
    system_laws = SYSTEM_LAWS | _laws_in(DEFAULT_LEGAL_BASIS)

    for section in draft.sections:
        text = section.text

        # ── Раздел-заглушка ──────────────────────────────────────
        #
        # Заглушка не содержит утверждений: в ней нет ни сумм, ни норм,
        # ни персон — только пометка о том, что модель не вызывалась.
        # Проверять её так же, как настоящий текст, бессмысленно и
        # вредно: номер в служебной пометке заглушки объявлялся
        # выдумкой модели с пометкой CRITICAL.
        #
        # Это выглядело как «система не работает», хотя честная причина
        # одна: раздел не сформирован. На демонстрации заказчику такая
        # проверка врёт дважды — выдумки не было и опасности нет.
        if section.is_mock:
            report.issues.append(
                Issue(
                    type=IssueType.UNSUPPORTED_CLAIM,
                    severity=Severity.MEDIUM,
                    text=text[:200],
                    reason=(
                        "раздел не сформирован: реальная модель не "
                        "вызвана, вместо текста — служебная заглушка"
                    ),
                    section=section.name,
                )
            )
            if section.error:
                report.issues.append(
                    Issue(
                        type=IssueType.INCOMPLETE,
                        severity=Severity.HIGH,
                        text=text[:200],
                        reason=f"ошибка генерации: {section.error}",
                        section=section.name,
                    )
                )
            continue

        report.claims_checked += 1

        # Номера статей из ссылок на нормы — не суммы. Без этого любая
        # корректная ссылка «статья 310 ГК РФ» помечалась бы как
        # «выдуманное число».
        law_numbers = {article for article, _ in _laws_in(text)}

        # ── 1. Раздел без единой ссылки на источник ────────────────
        if not section.citations and not pack.by_category(section.key):
            report.issues.append(
                Issue(
                    type=IssueType.MISSING_SOURCE,
                    severity=Severity.HIGH,
                    text=text[:200],
                    reason=(
                        "в материалах дела нет данных для раздела "
                        f"«{section.name}»"
                    ),
                    section=section.name,
                )
            )

        # ── 2. Раздел, помеченный моделью как требующий проверки ───
        if section.needs_review or NEEDS_REVIEW in text:
            report.issues.append(
                Issue(
                    type=IssueType.INCOMPLETE,
                    severity=Severity.MEDIUM,
                    text=text[:200],
                    reason="раздел помечен как требующий проверки специалистом",
                    section=section.name,
                )
            )

        # ── 3. Числа, которых нет в материалах (главная проверка) ──
        found_numbers = _numbers_in(text)
        # Числа, которые опираются на материалы дела. Сумма из них —
        # не выдумка, а арифметика проекта: «а всего» в резолюции
        # считается системой из уже подтверждённых сумм, и её не может
        # быть в материалах в готовом виде.
        backed = {
            int(number)
            for number in found_numbers
            if number in material_numbers
        }
        invented = {
            number
            for number in found_numbers
            if number not in material_numbers
            and number not in small_numbers
            and number not in law_numbers
            and not _is_sum_of(number, backed)
        }
        for number in sorted(invented):
            report.unsupported_claims += 1
            report.issues.append(
                Issue(
                    type=IssueType.UNSUPPORTED_CLAIM,
                    severity=Severity.CRITICAL,
                    text=text[:200],
                    reason=(
                        f"число {number} отсутствует в материалах дела — "
                        "возможна выдумка модели"
                    ),
                    section=section.name,
                )
            )

        # ── 4. Ссылки на нормы без подтверждения ───────────────────
        for article, code in _laws_in(text):
            if (article, code) in system_laws:
                # Норма, которую цитирует сама система по закону, а не
                # берёт из материалов дела. Подтверждать её материалами
                # бессмысленно: в иске судью ст. 198 ГПК не пишут.
                continue
            if (article, code) not in material_laws:
                report.issues.append(
                    Issue(
                        type=IssueType.LAW_NOT_FOUND,
                        severity=Severity.HIGH,
                        text=text[:200],
                        reason=(
                            f"ссылка на ст. {article} {code} не подтверждена "
                            "материалами дела"
                        ),
                        section=section.name,
                    )
                )

        # ── 5. Раздел не удалось сгенерировать ─────────────────────
        if section.error:
            report.issues.append(
                Issue(
                    type=IssueType.INCOMPLETE,
                    severity=Severity.HIGH,
                    text=text[:200],
                    reason=f"ошибка генерации: {section.error}",
                    section=section.name,
                )
            )

        # ── 6. Персоны, которых нет в материалах дела ─────────────
        persons, roles = check_section(text, section.name, pack)

        for finding in persons:
            report.unsupported_claims += 1
            report.issues.append(
                Issue(
                    type=IssueType.UNSUPPORTED_CLAIM,
                    severity=Severity.HIGH,
                    text=text[:200],
                    reason=finding.reason,
                    section=finding.section,
                )
            )

        for role_finding in roles:
            report.unsupported_claims += 1
            report.issues.append(
                Issue(
                    type=IssueType.CONTRADICTION,
                    severity=Severity.CRITICAL,
                    text=text[:200],
                    reason=role_finding.detail,
                    section=role_finding.section,
                )
            )

    # ── Итоговый статус ────────────────────────────────────────────
    critical = [i for i in report.issues if i.severity is Severity.CRITICAL]
    if critical or report.issues:
        report.status = VerificationStatus.REVIEW_REQUIRED

    return report


def compare_versions(text_a: str, text_b: str) -> dict[str, int]:
    """Сравнить две версии проекта (п.31).

    Простой подсчёт различий по предложениям: полноценный diff нужен
    только для отображения правок, а не для хранения — хранятся полные
    тексты версий.
    """
    sentences_a = [s.strip() for s in re.split(r"(?<=[.;])\s+", text_a) if s.strip()]
    sentences_b = [s.strip() for s in re.split(r"(?<=[.;])\s+", text_b) if s.strip()]
    set_a, set_b = set(sentences_a), set(sentences_b)
    return {
        "sentences_before": len(sentences_a),
        "sentences_after": len(sentences_b),
        "removed": len(set_a - set_b),
        "added": len(set_b - set_a),
        "unchanged": len(set_a & set_b),
    }
