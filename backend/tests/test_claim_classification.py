"""Тест классификации требований на живом деле DEMO-001.

Зачем. Дефект был найден не тестом, а прогоном демо: в категорию
«claims» из 46 фактов попадал один, и тот был фразой представителя,
а не требованием. Резолютивная часть при этом собиралась по правилам,
получала пустой набор требований и честно писала «требования истца не
установлены» — то есть система работала, но выглядела так, будто в деле
нет предмета спора.

Утверждения взяты из материалов синтетического дела. Это проверка на
реальном тексте: регулярные выражения проверяются не идеальной фразой
из теста, а тем, что судья действительно пишет в иске.
"""

from __future__ import annotations

from app.agents.claim_phrases import claim_basis, looks_like_claim
from app.agents.evidence_pack import _classify

# Фразы из материалов DEMO-001 и типичных исковых заявлений.
REAL_CLAIM_SENTENCES = [
    "Истец требует взыскать с Ответчика задолженность по договору "
    "поставки № Д-2026/001 в размере 150000 руб.",
    "Истец просит взыскать неустойку за просрочку оплаты "
    "в размере 10% от суммы задолженности.",
    "Прошу взыскать убытки, причинённые ненадлежащим исполнением "
    "обязательства, в размере 30000 руб.",
    "Истец требует возместить расходы на представителя в размере 20000 руб.",
    "Требую признать недействительным договор поставки в части.",
]

# Фразы, которые требованиями НЕ являются, хотя и встречаются в деле.
NOT_CLAIM_SENTENCES = [
    "Истец считает, что ответчик действует недобросовестно.",
    "Договор поставки заключен 15 мая 2026 года.",
    "Ответчик не возражал против предъявленных требований.",
    "Представитель истца поддерживает исковые требования, указывая "
    "на наличие доказательств.",
    "Оплата по договору произведена в полном объёме.",
]


class TestRealClaimsAreRecognised:
    def test_all_real_claims_pass_gate(self) -> None:
        for sentence in REAL_CLAIM_SENTENCES:
            assert looks_like_claim(sentence), f"не опознано: {sentence}"

    def test_all_real_claims_reach_claims_category(self) -> None:
        """Именно это проверялось в демо: категория «claims» была пуста."""
        for sentence in REAL_CLAIM_SENTENCES:
            assert _classify(sentence, "CLAIM") == "claims", (
                f"не попало в claims: {sentence}"
            )

    def test_every_claim_gets_a_basis(self) -> None:
        """Требование без основания молча выпало бы из резолюции."""
        for sentence in REAL_CLAIM_SENTENCES:
            assert claim_basis(sentence) is not None, (
                f"основание не определено: {sentence}"
            )

    def test_amount_found_in_real_sentences(self) -> None:
        """Сумма должна находиться в тех же фразах."""
        from app.drafting.requirements import _find_amount

        assert _find_amount(REAL_CLAIM_SENTENCES[0]) == 150000
        assert _find_amount(REAL_CLAIM_SENTENCES[2]) == 30000
        assert _find_amount(REAL_CLAIM_SENTENCES[3]) == 20000


class TestNonClaimsAreRejected:
    def test_arguments_not_mistaken_for_claims(self) -> None:
        for sentence in NOT_CLAIM_SENTENCES:
            assert not looks_like_claim(sentence), f"ложное срабатывание: {sentence}"

    def test_arguments_do_not_reach_claims_category(self) -> None:
        for sentence in NOT_CLAIM_SENTENCES:
            assert _classify(sentence, "CLAIM") != "claims", (
                f"попало в claims: {sentence}"
            )


class TestEarlierFalsePositives:
    """Регрессии, найденные на живых текстах при разработке."""

    def test_prosrochka_is_not_prosba(self) -> None:
        """«просрочка» — существительное, а не требование."""
        text = "Истец указывает на просрочку в оплате по договору."
        assert not looks_like_claim(text)

    def test_obyazatelstva_is_not_obyazat(self) -> None:
        """«обязательства» — существительное, а не глагол требования."""
        text = "Ответчик не исполнил свои обязательства по договору."
        assert not looks_like_claim(text)

    def test_udovletvorit_is_not_claim(self) -> None:
        """Обоснование «считает возможным удовлетворить» — не требование."""
        text = "Истец считает возможным удовлетворить иск частично."
        assert not looks_like_claim(text)
