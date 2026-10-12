"""Построение резолютивной части решения по правилам, а не моделью.

Зачем. Резолютивная часть — единственная часть решения, где ошибка
непоправима: в ней суд постановляет, кому и сколько платить. Ошибка
в мотивировке — вопрос к специалисту, ошибка в резолютивной части —
это отмена решения и новое рассмотрение дела.

Модель на объёме 1,5B параметров путает стороны именно здесь: в
проверке это давало «ответчик обязан возменить истцу сумму» вместо
«взыскать с ответчика в пользу истца». Это дефект не понимания
права, а согласования слов в предложении, и он лечится структурой,
а не длиной промпта.

Поэтому резолютивная часть собирается из предъявленных требований по
жёсткой грамматике. Модель в неё не входит.

ПРАВИЛА, ВЗЯТЫЕ ИЗ НАСТОЯЩИХ РЕШЕНИЙ
    Формулировки сверены с 1 425 гражданскими делами из датасета
    TryDotAtwo/russian-legal-ner. Числа и выводы: docs/real-resolutions-rules.md,
    разбор воспроизводится скриптом scripts/extract_rules.py.

    Что подтвердилось:
      - «взыскать с X в пользу Y» — устойчивая конструкция (700 из 1 425);
      - копейки пишутся почти так же часто, как рубли (613 против 628);
      - пошлина включается в резолюцию, а не выносится из неё (595);
      - стороны называются конкретно: ФИО (277) или организацией (403)
        чаще, чем обобщённым словом (358).

    Что добавлено по итогам разбора:
      - копейки в сумме;
      - итог «а всего …» (189 документов) — сумма взыскания с учётом
        пошлин и пеней одной цифрой;
      - сумма прописью в скобках (181 документ);
      - наименование сторон вместо слов «истец» и «ответчик».

    Что НЕ принято, хотя встречается чаще:
      - сплошное предложение вместо пунктов. Частота упоминания пошлины
        в резолюции (595) не означает, что она выносится туда всегда;
        отдельный пункт со ссылкой на ст. 98 ГПК удобнее для проверки
        и понятнее судье. Это осознанное расхождение с практикой,
        а не недосмотр.

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

# Пометка о непроверенном значении. Единая на весь проект.
REVIEW = "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ"

# Основание решения по существу.
#
# Раньше здесь стояли ст. 209, 210, 211 ГПК РФ — они были взяты из
# шаблона без проверки, и разбор настоящих решений это опроверг:
# в 1 425 гражданских резолюциях эти статьи не встречаются ни разу.
# Наиболее часто суды называют ст. 198 ГПК РФ (521 упоминание в
# гражданских делах) — это разрешение спора по существу судом первой
# инстанции, то есть именно то основание, ради которого выносится
# решение.
#
# Значение НЕ универсально: для заочного производства добавляют
# ст. 233, для приказного — свои. Поэтому основание вынесено в
# аргумент и может быть задано вызывающим кодом.
DEFAULT_LEGAL_BASIS = "ст. 198 ГПК РФ"


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

# Единственные и множественные формы числительных: количество копеек
# не совпадает с количеством рублей («79 коп.» при «5034 руб.»).
_RUB_FORMS: tuple[str, ...] = ("рубль", "рубля", "рублей")
_KOP_FORMS: tuple[str, ...] = ("копейка", "копейки", "копеек")


def _plural(number: int, forms: tuple[str, str, str]) -> str:
    """Выбрать форму числительного: 1 рубль, 2 рубля, 5 рублей."""
    tail100 = number % 100
    tail10 = number % 10
    if 11 <= tail100 <= 14:
        return forms[2]
    if tail10 == 1:
        return forms[0]
    if 2 <= tail10 <= 4:
        return forms[1]
    return forms[2]


def _to_feminine(word: str) -> str:
    """Числительное в женском роде: «два» -> «две».

    Нужно для тысяч: тысяча женского рода. Три слова из списка на
    сотни меняют форму — «двести тысяч», «двести двадцать тысяч».
    """
    mapping = {
        "один": "одна",
        "два": "две",
        "триста": "триста",
        "четыреста": "четыреста",
    }
    return mapping.get(word, word)


def _under_thousand(value: int) -> list[str]:
    """Разложить число до 999 словами."""
    units = (
        "", "один", "два", "три", "четыре", "пять", "шесть", "семь",
        "восемь", "девять", "десять", "одиннадцать", "двенадцать",
        "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
        "семнадцать", "восемнадцать", "девятнадцать",
    )
    teens = (
        "", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят",
        "семьдесят", "восемьдесят", "девяносто",
    )
    hundreds = (
        "", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот",
        "семьсот", "восемьсот", "девятьсот",
    )

    words: list[str] = []
    if value >= 100:
        words.append(hundreds[value // 100])
    remainder = value % 100
    if remainder >= 20:
        words.append(teens[remainder // 10])
        if remainder % 10:
            words.append(units[remainder % 10])
    elif remainder:
        words.append(units[remainder])
    return words


def rubles_to_words(value: float) -> str:
    """Сумма прописью — так пишут в резолютивной части в скобках.

    Формат из решений: «5467 (пять тысяч четыреста шестьдесят семь)
    руб. 05 коп.». Прописная форма даётся без учёта родительного
    падежа, потому что в скобках стоит именно такая.

    Ограничение: разложение делается до миллионов. Суммы выше в
    гражданских исках редки, а полноценное разложение с миллиардами
    и склонениями здесь было бы объёмом кода без практической пользы.
    """
    whole = int(value)
    if whole >= 1_000_000:
        return f"{whole:,}".replace(",", " ")
    if whole == 0:
        return "ноль"

    words: list[str] = []
    if whole >= 1000:
        thousands = whole // 1000
        # Тысяча женского рода, поэтому разложение тысяч переводится
        # в женскую форму: «одна тысяча», «две тысячи», «двадцать одна
        # тысяча». Мужская форма здесь давала «один тысяча».
        thousands_words = [_to_feminine(w) for w in _under_thousand(thousands)]
        words.extend(thousands_words)

        tail100 = thousands % 100
        tail10 = thousands % 10
        if 11 <= tail100 <= 14:
            words.append("тысяч")
        elif tail10 == 1:
            words.append("тысяча")
        elif 2 <= tail10 <= 4:
            words.append("тысячи")
        else:
            words.append("тысяч")

    remainder = whole % 1000
    if remainder:
        words.extend(_under_thousand(remainder))

    return " ".join(words)


@dataclass(frozen=True)
class Parties:
    """Названия сторон для резолютивной части.

    Суд называет стороны конкретно: ФИО или организацию. Обобщённые
    слова «истец» и «ответчик» в решениях встречаются реже, чем
    конкретные названия (358 против 680 из 1 425 документов).

    Если название не установлено, подставляется роль. Это осознанно:
    пустое место в резолюции хуже, чем родовое слово.
    """

    #: Название в родительном падеже: «Абдулиной И.И.», «ООО «Газпром»».
    plaintiff: str = ""
    defendant: str = ""

    @property
    def plaintiff_genitive(self) -> str:
        return self.plaintiff.strip() or PartyRole.PLAINTIFF.genitive

    @property
    def defendant_genitive(self) -> str:
        return self.defendant.strip() or PartyRole.DEFENDANT.genitive


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
    #: Копейки. Хранятся отдельно от целых рублей, потому что
    #: «5034 руб. 79 коп.» — это 5034,79, и округление до целого
    #: исказило бы взыскание.
    kopecks: int = 0
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


@dataclass
class OperativePart:
    """Собранная резолютивная часть и её пропуски."""

    items: list[str] = field(default_factory=list)
    #: Что не удалось определить. Пустой список означает, что пункт
    #: пригоден к рассмотрению; непустой — требует вмешательства судьи.
    gaps: list[str] = field(default_factory=list)
    #: Ссылка на норму, которой суд обосновывает решение по существу.
    legal_basis: str = DEFAULT_LEGAL_BASIS

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
        legal = f"Руководствуясь {self.legal_basis}, суд решил:"
        if self.gaps:
            return f"{legal}\n{body}\n\n{REVIEW}: " + "; ".join(self.gaps)
        return f"{legal}\n{body}"


def _amount(value: float, kopecks: int = 0) -> str:
    """Сумма в принятой форме.

    Цифрами и копейками: «150 000 руб. 79 коп.». Разряды разделяются
    пробелом, копейки пишутся двумя цифрами — так в судебных актах,
    и так показывает разбор 1 425 решений.
    """
    whole = int(value)
    formatted = f"{whole:,}".replace(",", " ")
    return f"{formatted} руб. {kopecks:02d} коп."


def _amount_with_words(value: float, kopecks: int = 0) -> str:
    """Сумма с прописью в скобках: «5 467 (пять тысяч…) руб. 05 коп.»."""
    whole = int(value)
    formatted = f"{whole:,}".replace(",", " ")
    words = rubles_to_words(whole)
    return f"{formatted} ({words}) руб. {kopecks:02d} коп."


def _sum_kopecks(values: list[tuple[float, int]]) -> int:
    """Сложить копейки по требованиям.

    Копейки хранятся отдельно от рублей, поэтому итог нельзя получить
    простым сложением сумм: 5034 руб. 79 коп. плюс 400 руб. — это
    5 434 руб. 79 коп., а не 5 434 руб. 00 коп. Ошибка была найдена
    тестом на данных реального решения.
    """
    total = 0
    for _, kopecks in values:
        total += kopecks
    return total % 100


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


def _satisfy(
    claim: MoneyClaim, outcome: Outcome, parties: Parties
) -> tuple[str, list[str]]:
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
        amount_text = _amount(claim.amount, claim.kopecks)

    if not claim.source:
        gaps.append(f"не указан источник суммы по требованию «{claim.basis}»")

    payer = parties.defendant_genitive
    payee = parties.plaintiff_genitive

    if outcome is Outcome.SATISFIED:
        return (
            f"Удовлетворить исковые требования истца: взыскать с {payer} "
            f"в пользу {payee} {amount_text} {_reference(claim)}.",
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
        granted_text = _amount(claim.granted_amount, claim.kopecks)

    detail = f"; {claim.grounds}" if claim.grounds else ""
    reference = f"({claim.basis}{detail})"
    return (
        f"Удовлетворить исковые требования истца частично: взыскать с "
        f"{payer} в пользу {payee} {granted_text} "
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
    parties: Parties | None = None,
    total_line: bool = True,
    legal_basis: str = DEFAULT_LEGAL_BASIS,
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
        parties: названия сторон. Пустые поля подставляют родовые
            слова «истец» и «ответчик».
        total_line: выводить ли итог «а всего …». По разбору решений
            итог присутствует в 189 случаях из 1 425 и суммирует
            взыскание с пошлинами, поэтому за него берётся сумма
            всех требований плюс пошлина.
        legal_basis: норма, которой суд обосновывает решение. По
            умолчанию ст. 198 ГПК РФ; для особых производств
            (заочное, приказное) задаётся своя.

    Возвращает:
        OperativePart с пунктами и списком пропусков.
    """
    result = OperativePart(legal_basis=legal_basis)
    named = parties or Parties()

    if not money_claims and not other_claims:
        result.gaps.append("в материалах дела не найдено ни одного требования")
        return result

    # 1. Требования по существу.
    granted: list[tuple[float, int]] = []
    for claim in money_claims:
        text, gaps = _satisfy(claim, claim.outcome, named)
        result.items.append(text)
        result.gaps.extend(gaps)
        # В итог входит только то, что реально взыскивается: отказ и
        # частичное удовлетворение не дают полной суммы.
        if claim.outcome is Outcome.SATISFIED and claim.amount is not None:
            granted.append((claim.amount, claim.kopecks))
        elif (
            claim.outcome is Outcome.PARTIAL
            and claim.granted_amount is not None
        ):
            granted.append((claim.granted_amount, claim.kopecks))

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
    if fee_stakes:
        if fee_paid is None:
            result.gaps.append(
                "не установлен размер государственной пошлины — "
                "пункт о распределении расходов требует проверки"
            )
        else:
            item = (
                f"Взыскать с {named.defendant_genitive} в пользу "
                f"{named.plaintiff_genitive} расходы по уплате "
                f"государственной пошлины в размере {_amount(fee_paid)} "
                f"(ст. 98 ГПК РФ)."
            )
            if costs is not None:
                item += (
                    f" Взыскать с {named.defendant_genitive} в пользу "
                    f"{named.plaintiff_genitive} иные расходы в размере "
                    f"{_amount(costs)} (ст. 100 ГПК РФ)."
                )
            result.items.append(item)
            granted.append((fee_paid, 0))
            if costs is not None:
                granted.append((costs, 0))

    # 4. Итог «а всего». Так пишут в резолюции: одна цифра, из которой
    #    видно общий размер взыскания.
    if total_line and granted:
        total_rubles = sum(value for value, _ in granted)
        result.items.append(
            f"Всего подлежит взысканию "
            f"{_amount_with_words(total_rubles, _sum_kopecks(granted))}"
        )

    # 5. Право на обжалование. Не заполняется моделью никогда.
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

    # Итог и копейки — по разбору настоящих решений.
    with_kop = MoneyClaim(amount=5034, kopecks=79, basis="задолженность",
                          source="начисление")
    kop_text = build_operative([with_kop], fee_paid=400).render()
    if "5 034 руб. 79 коп." not in kop_text:
        problems.append("копейки: сумма не отформатирована с копейками")
    if "а всего" not in kop_text and "Всего подлежит взысканию" not in kop_text:
        problems.append("итог: строка «всего» не построена")

    return problems
