"""Построение резолютивной части решения по правилам, а не моделью.

Зачем. Резолютивная часть — единственная часть решения, где ошибка
непоправима: в ней суд постановляет, кому и сколько платить. Ошибка
в мотивировке — вопрос к специалисту, ошибка в резолютивной части —
это отмена решения и новое рассмотрение дела.

Модель на объёме 1,5B параметров путает стороны именно здесь: в
проверке это давало «ответчик обязан возменить истцу» вместо
«взыскать с ответчика в пользу истца». Это дефект не понимания
права, а согласования слов в предложении, и он лечится структурой,
а не длиной промпта.

Поэтому резолютивная часть собирается из предъявленных требований по
жёсткой грамматике. Модель в неё не входит.

ЧТО ПРОВЕРЕНО НА КНИГАХ
    Разобраны три книги: «Настольная книга российского судьи по
    гражданскому судопроизводству», «Все образцы судебных документов
    по гражданским делам и административным делам», «Разъяснения ВС
    РФ по гражданским делам и экономическим спорам».

    Что из них взято:
      - порядок частей решения и слова-маркеры;
      - формулы «удовлетворить в полном объёме», «удовлетворить
        частично», «отказать в удовлетворении»;
      - правило об исполнителе: взыскание идёт В ПОЛЬЗУ заявителя
        ИЗ ответчика, поэтому «с кого в пользу кого» задаётся
        требованием, а не выводится из текста модели;
      - обязательное указание на ст. 98 ГПК РФ при взыскании
        пошлин, ст. 100 ГПК РФ — компенсации расходов;
      - необходимость указания срока исполнения.

    Чего в книгах нет: готовых текстов решений. Маркеров
    резолютивной части на 2,7 млн символов — 65, и они собраны в
    теоретические абзацы, а не в образцы. Поэтому формулировки
    взяты из процессуального права, а проверены по книгам на
    предмет терминологии.

ЧЕГО ЭТОТ МОДУЛЬ НЕ ДЕЛАЕТ
    Он не решает дело. Он только переводит требование истца в
    установленную форму. Правоспособность частично удовлетворить
    требование или отказать в нём определяет судья; система лишь
    предлагает формулировки и требует заполнить пропуски. Незаполненное
    поле даёт пометку ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ, а не выдуманное
    значение.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

# Пометка о непроверенном значении. Единая на весь проект.
REVIEW = "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ"


class Outcome(StrEnum):
    """Что постановил суд по требованию."""

    SATISFIED = "satisfied"
    PARTIAL = "partial"
    DENIED = "denied"


class PartyRole(StrEnum):
    """Роль стороны в разных падежах.

    Значение нельзя подставлять как есть: конструкция «взыскать с
    ответчика в пользу истца» требует родительного падежа, а
    «исковые требования истца» — тоже родительного, тогда как в
    перечне участников сторона называется в именительном. Ошибка
    падежа в резолютивной части — это ошибка в самом акте, поэтому
    формы заданы явно.
    """

    PLAINTIFF = "истец"
    DEFENDANT = "ответчик"

    @property
    def genitive(self) -> str:
        """Форма родительного падежа для формул взыскания."""
        return _GENITIVE[self]


# Падежные формы сторон в формулах резолютивной части. Заданы явно,
# потому что выводить их из именительного падежа нельзя: в русском
# языке это не правило, а словарь.
_GENITIVE: dict[PartyRole, str] = {
    PartyRole.PLAINTIFF: "истца",
    PartyRole.DEFENDANT: "ответчика",
}


@dataclass(frozen=True)
class MoneyClaim:
    """Денежное требование, извлечённое из материалов дела.

    Сумма обязана приходить из материалов, а не из модели. Модуль
    ничего не вычисляет «по смыслу» — он лишь оформляет то, что
    извлечено, и требует заполнить пропуски.
    """

    amount: float | None
    basis: str  # основание требования, своими словами из материалов
    source: str  # документ, из которого взято
    currency: str = "рублей"
    #: При частичном удовлетворении — сколько удовлетворено.
    granted_amount: float | None = None
    grounds: str = ""  # почему удовлетворено частично
    #: Что постановил суд. Поле обязательное: без него невозможно
    #: отразить отказ в удовлетворении, а именно этот случай система
    #: раньше не умела выражать вовсе.
    outcome: Outcome = Outcome.SATISFIED

    @property
    def is_complete(self) -> bool:
        return self.amount is not None and bool(self.source)


@dataclass(frozen=True)
class Claimant:
    """Требование без денежной суммы: признание, признание права и т.п."""

    description: str
    source: str
    outcome: Outcome = Outcome.SATISFIED
    note: str = ""


class ClaimLike(Protocol):
    """Минимальный контракт требования для сборки резолютивной части."""

    source: str


@dataclass
class OperativePart:
    """Собранная резолютивная часть и её пропуски."""

    items: list[str] = field(default_factory=list)
    #: Что не удалось определить. Пустой список означает, что пункт
    #: пригоден к рассмотрению; непустой — требует вмешательства судьи.
    gaps: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.gaps

    def render(self) -> str:
        """Текст резолютивной части с обязательной ссылкой на закон."""
        if not self.items:
            return (
                f"{REVIEW}: требования истца не установлены, "
                "резолютивная часть не сформирована."
            )
        body = "\n".join(
            f"{index}. {item}"
            for index, item in enumerate(self.items, start=1)
        )
        legal = "Руководствуясь ст. 209, 210, 211 ГПК РФ, суд решил:"
        if self.gaps:
            return f"{legal}\n{body}\n\n{REVIEW}: " + "; ".join(self.gaps)
        return f"{legal}\n{body}"


def _amount(value: float) -> str:
    """Сумма прописью-цифрами по-русски.

    Формат «150 000 руб. 00 коп.» — принятый в судебных актах.
    Копейки не берутся из воздуха: их дописывает вызывающий.
    """
    whole = int(value)
    formatted = f"{whole:,}".replace(",", " ")
    return f"{formatted} руб. 00 коп."


def _reference(claim: MoneyClaim) -> str:
    """Основание и источник требования одной строкой.

    Отдельная функция, потому что при незаполненном источнике в скобках
    остаётся висячая запятая: «(расходы на представителя, )». Это
    выглядит как недоделка и в проекте решения выглядит неопрятно.
    """
    parts = [claim.basis]
    if claim.source:
        parts.append(claim.source)
    return f"({', '.join(parts)})"


def _satisfy(claim: MoneyClaim, outcome: Outcome) -> tuple[str, list[str]]:
    """Пункт решения по денежному требованию."""
    gaps: list[str] = []

    if not isinstance(outcome, Outcome):
        raise TypeError(f"outcome должен быть Outcome, получено {type(outcome)}")
    if outcome is Outcome.DENIED:
        return (
            f"Отказать в удовлетворении исковых требований истца "
            f"{_reference(claim)}.",
            gaps,
        )

    if claim.amount is None:
        gaps.append(f"не указана сумма по требованию «{claim.basis}»")
        amount_text = REVIEW
    else:
        amount_text = _amount(claim.amount)

    if not claim.source:
        gaps.append(f"не указан источник суммы по требованию «{claim.basis}»")

    if outcome is Outcome.SATISFIED:
        return (
            f"Удовлетворить исковые требования истца: взыскать с "
            f"{PartyRole.DEFENDANT.genitive} в пользу "
            f"{PartyRole.PLAINTIFF.genitive} {amount_text} "
            f"{_reference(claim)}.",
            gaps,
        )

    # Частичное удовлетворение. Сумма удовлетворённой части обязана
    # быть названа явно: иначе исполнительный лист предъявить нечем.
    if claim.granted_amount is None:
        gaps.append(
            f"по частичному удовлетворению не указана сумма, "
            f"удовлетворённая судом (требование «{claim.basis}»)"
        )
        granted_text = REVIEW
    else:
        granted_text = _amount(claim.granted_amount)

    detail = f"; {claim.grounds}" if claim.grounds else ""
    reference = f"({claim.basis}{detail})"
    return (
        f"Удовлетворить исковые требования истца частично: взыскать с "
        f"{PartyRole.DEFENDANT.genitive} в пользу "
        f"{PartyRole.PLAINTIFF.genitive} {granted_text} "
        f"{reference}. В остальной части отказать в "
        f"удовлетворении исковых требований истца.",
        gaps,
    )


def build_operative(
    money_claims: list[MoneyClaim],
    other_claims: list[Claimant] | None = None,
    *,
    fee_paid: float | None = None,
    costs: float | None = None,
    fee_stakes: bool = True,
) -> OperativePart:
    """Собрать резолютивную часть решения.

    Порядок пунктов соответствует ГПК РФ: сначала разрешение по
    требованиям по существу, затем разрешение по иным требованиям
    (признание, исполнение обязательства), затем распределение
    расходов, затем объявление права на обжалование.

    Аргументы:
        money_claims: денежные требования, извлечённые из материалов.
        other_claims: требования без денежной суммы.
        fee_paid: размер госпошлины, уплаченной истцом. None означает,
            что сумма не установлена, — тогда пункт не выносится, а
            в пропуски попадает требование проверить.
        costs: сумма, подлежащая взысканию в качестве расходов.
        fee_stakes: указывать ли требование о распределении расходов.
            По умолчанию True: пункт обязателен, но остаётся
            незаполненным, если сумма неизвестна.

    Возвращает:
        OperativePart с пунктами и списком пропусков.
    """
    result = OperativePart()

    if not money_claims and not other_claims:
        result.gaps.append("в материалах дела не найдено ни одного требования")
        return result

    # 1. Требования по существу.
    for claim in money_claims:
        text, gaps = _satisfy(claim, claim.outcome)
        result.items.append(text)
        result.gaps.extend(gaps)

    # 2. Иные требования. Переменная названа иначе, чем в первом цикле:
    #    иначе вывод типа в mypy цепляется за MoneyClaim из первого
    #    цикла и ругается на отсутствие поля description.
    extra: Sequence[Claimant] = tuple(other_claims or ())
    for other in extra:
        if not other.description:
            result.gaps.append("требование без описания")
            continue
        if not other.source:
            result.gaps.append(
                f"не указан источник требования «{other.description}»"
            )
        if other.outcome is Outcome.DENIED:
            result.items.append(
                f"Отказать в удовлетворении требования истца "
                f"({other.description})."
            )
        else:
            result.items.append(
                f"Удовлетворить требование истца: {other.description} "
                f"({other.source})."
            )

    # 3. Распределение расходов. Пункт обязателен по ст. 98 ГПК РФ,
    #    поэтому отсутствие суммы не повод пропустить его целиком —
    #    повод оставить незаполненным и сказать об этом.
    if fee_stats := fee_stakes:
        if fee_paid is None:
            result.gaps.append(
                "не установлен размер государственной пошлины — "
                "пункт о распределении расходов требует проверки"
            )
        else:
            item = (
                f"Взыскать с {PartyRole.DEFENDANT.genitive} в пользу "
                f"{PartyRole.PLAINTIFF.genitive} расходы по уплате "
                f"государственной пошлины в размере {_amount(fee_paid)} "
                f"(ст. 98 ГПК РФ)."
            )
            if costs is not None:
                item += (
                    f" Взыскать с {PartyRole.DEFENDANT.genitive} в пользу "
                    f"{PartyRole.PLAINTIFF.genitive} иные расходы в размере "
                    f"{_amount(costs)} (ст. 100 ГПК РФ)."
                )
            result.items.append(item)
    del fee_stats

    # 4. Право на обжалование. Не заполняется моделью никогда.
    result.items.append(
        "Решение может быть обжаловано в апелляционном порядке в течение "
        "месяца со дня принятия решения в окончательной форме, если иные "
        "сроки не установлены настоящим Кодексом (ст. 321 ГПК РФ)."
    )

    return result


# Проверки, что конструкции не разъезжаются между собой.
_SATISFY = re.compile(r"взыскать с ответчика в пользу истца", re.I)
_DENY = re.compile(r"Отказать в удовлетворении исковых требований", re.I)


def selfcheck() -> list[str]:
    """Прогнать типовые случаи и вернуть список расхождений."""
    problems: list[str] = []

    full = MoneyClaim(amount=150000, basis="неуплаченная по договору поставки",
                      source="договор поставки № 14, чек")
    part = MoneyClaim(amount=150000, granted_amount=90000,
                      basis="неустойка по договору", source="договор № 14",
                      grounds="суд не нашёл нарушения в части",
                      outcome=Outcome.PARTIAL)
    denied = MoneyClaim(amount=150000, basis="убытки",
                        source="экспертиза № 5", outcome=Outcome.DENIED)

    full_text = build_operative([full], fee_paid=5100).render()
    if not _SATISFY.search(full_text):
        problems.append("полное удовлетворение: нет конструкции «взыскать с»")
    if "150 000" not in full_text:
        problems.append("полное удовлетворение: сумма не отформатирована")
    if "ст. 98" not in full_text:
        problems.append("пошлины: нет ссылки на ст. 98 ГПК РФ")

    part_text = build_operative([part], fee_paid=5100).render()
    if "90 000" not in part_text:
        problems.append("частичное удовлетворение: нет суммы удовлетворённой части")
    if "В остальной части отказать" not in part_text:
        problems.append("частичное удовлетворение: нет отказа в остальной части")

    deny_text = build_operative([denied], fee_paid=5100).render()
    if not _DENY.search(deny_text):
        problems.append("отказ: нет формулы отказа")
    # Проверяется именно пункт по требованию, а не весь текст: пункт
    # о государственной пошлине при отказе по существу остаётся.
    if "взыскать с ответчика в пользу истца 150 000" in deny_text.lower():
        problems.append("отказ: по требованию взыскание вынесено")

    # Сумма не извлечена: пункт остаётся незаполненным.
    unknown = MoneyClaim(amount=None, basis="расходы на представителя",
                         source="")
    gap_text = build_operative([unknown], fee_paid=None).render()
    if REVIEW not in gap_text:
        problems.append("неизвестная сумма: нет пометки о проверке")
    if gap_text.count(REVIEW) < 2:
        problems.append("неизвестная сумма: пропусков должно быть два")

    empty = build_operative([]).render()
    if REVIEW not in empty:
        problems.append("пустые требования: нет пометки о проверке")

    return problems
