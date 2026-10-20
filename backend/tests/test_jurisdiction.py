"""Проверка родовой подсудности (п. 5 ч. 1 ст. 23 ГПК РФ)."""

from app.verification.jurisdiction import check_jurisdiction, expected_tier


class TestExpectedTier:
    """Порог 100 000 руб. — мировой судья, свыше — районный."""

    def test_small_claim_world_judge(self) -> None:
        assert expected_tier(100_000) == "мировой судья"

    def test_over_limit_district(self) -> None:
        assert expected_tier(100_001) == "районный суд"

    def test_zero_no_tier(self) -> None:
        assert expected_tier(0) == "районный суд"


class TestCheckJurisdiction:
    """Расхождение видно, совпадение молчит, отсутствие тоже молчит."""

    def test_mismatch_world_judge_over_limit(self) -> None:
        findings = check_jurisdiction(
            ["Иск подан мировому судье судебного участка № 12"],
            claim_total=150_000,
        )
        assert len(findings) == 1
        assert findings[0].expected == "районный суд"
        assert "мировой" in findings[0].found

    def test_mismatch_district_small_claim(self) -> None:
        findings = check_jurisdiction(
            ["Дело рассматривается районным судом"], claim_total=50_000
        )
        assert len(findings) == 1
        assert findings[0].expected == "мировой судья"

    def test_match_is_silent(self) -> None:
        assert not check_jurisdiction(
            ["Мировой судья судебного участка № 3"], claim_total=80_000
        )

    def test_no_court_mention_is_silent(self) -> None:
        # Суд не назван в материалах — замечания нет: признака нет,
        # выдумывать инстанцию система не умеет.
        assert not check_jurisdiction(
            ["Истец просит взыскать долг по договору"], claim_total=150_000
        )

    def test_no_claims_is_silent(self) -> None:
        # Цена иска неизвестна — сверять нечего.
        assert not check_jurisdiction(
            ["Районный суд"], claim_total=0
        )

    def test_court_found_in_any_document(self) -> None:
        # Суд может быть назван не в первом документе дела.
        findings = check_jurisdiction(
            ["Прошу взыскать долг", "определение мирового судьи"],
            claim_total=200_000,
        )
        assert len(findings) == 1

    def test_match_in_later_document(self) -> None:
        assert not check_jurisdiction(
            ["Прошу взыскать долг", "решение районного суда"],
            claim_total=200_000,
        )
