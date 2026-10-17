"""Тест: правка судьи не стирает разделы и источники.

Дефект найден при подготовке демонстрации, а не по теоретическим
соображениям: в рабочей базе лежали восемь проектов, созданных
проверкой интерфейса, и во всех восьми последняя версия — правка
судьи — хранилась с пустым списком разделов. Интерфейс показывал
«разделов 0 · источников 0».

Это худший момент для потери ссылок: судья правит текст, чтобы
принять проект, и именно тогда все ссылки на материалы дела
исчезают. Проверяется в первую очередь сохранение источников.
"""

from __future__ import annotations

from app.drafting.sections import resplit_sections

PREVIOUS = [
    {
        "key": "introductory",
        "name": "Вводная часть",
        "text": "Дело № DEMO-001 рассмотрено в суде.",
        "is_mock": False,
        "needs_review": False,
        "citations": ["01_claim.txt", "05_protocol.txt"],
        "latency_ms": 10,
    },
    {
        "key": "operative",
        "name": "РЕШИЛ",
        "text": "Взыскать 150 000 руб. 00 коп.",
        "is_mock": False,
        "needs_review": False,
        "citations": ["01_claim.txt"],
        "latency_ms": 12,
    },
]

TEXT = (
    "ВВОДНАЯ ЧАСТЬ\n\n"
    "Дело № DEMO-001 рассмотрено в суде.\n\n"
    "РЕШИЛ\n\n"
    "Взыскать с ответчика 150 000 руб. 00 коп."
)


class TestSourcesSurviveEdit:
    def test_sources_kept(self) -> None:
        """Главное: ссылки на материалы дела переживают правку."""
        sections = resplit_sections(TEXT, PREVIOUS)
        by_key = {s["key"]: s for s in sections}
        assert by_key["introductory"]["citations"] == [
            "01_claim.txt",
            "05_protocol.txt",
        ]
        assert by_key["operative"]["citations"] == ["01_claim.txt"]

    def test_all_sections_returned(self) -> None:
        sections = resplit_sections(TEXT, PREVIOUS)
        assert [s["key"] for s in sections] == ["introductory", "operative"]

    def test_edited_text_taken_from_new_version(self) -> None:
        """Текст раздела — из правки, а не из прошлой версии."""
        sections = resplit_sections(TEXT, PREVIOUS)
        operative = next(s for s in sections if s["key"] == "operative")
        assert operative["text"] == "Взыскать с ответчика 150 000 руб. 00 коп."

    def test_untouched_section_not_flagged(self) -> None:
        """Не тронутый судьёй раздел не должен получить лишнюю пометку.

        Иначе пометка «требует проверки» появится везде, и судья
        перестанет её читать — а это единственный сигнал, который
        показывает, где нужна его собственная работа.
        """
        sections = resplit_sections(TEXT, PREVIOUS)
        introductory = next(s for s in sections if s["key"] == "introductory")
        assert introductory["needs_review"] is False


class TestChangedSectionFlagged:
    def test_changed_text_needs_review(self) -> None:
        """Правка судьи не проверялась автоматически."""
        sections = resplit_sections(TEXT, PREVIOUS)
        operative = next(s for s in sections if s["key"] == "operative")
        assert operative["needs_review"] is True

    def test_previous_flag_is_kept(self) -> None:
        """Пометка, поставленная проверкой, правкой не снимается."""
        previous = [dict(PREVIOUS[0])]
        sections = resplit_sections(
            "ВВОДНАЯ ЧАСТЬ\n\nДело № DEMO-001 рассмотрено в суде.",
            previous,
        )
        assert sections[0]["needs_review"] is False

        previous[0]["needs_review"] = True
        sections = resplit_sections(
            "ВВОДНАЯ ЧАСТЬ\n\nДело № DEMO-001 рассмотрено в суде.",
            previous,
        )
        assert sections[0]["needs_review"] is True

    def test_deleted_section_stays_visible(self) -> None:
        """Удалённый судьёй заголовок не исчезает молча.

        Если раздел убрали, судья должен увидеть, что в проекте
        не хватает части акта, а не получить укороченный текст,
        который выглядит как готовый.
        """
        sections = resplit_sections(
            "ВВОДНАЯ ЧАСТЬ\n\nДело № DEMO-001 рассмотрено в суде.",
            PREVIOUS,
        )
        operative = next(s for s in sections if s["key"] == "operative")
        assert operative["text"] == ""
        assert operative["needs_review"] is True


class TestUnsplitTable:
    def test_text_without_headings(self) -> None:
        """Нет заголовков — текст виден, источники не приписаны.

        Приписать произвольный текст к конкретным документам нельзя:
        это ровно то выдумывание, которого продукт не делает.
        """
        sections = resplit_sections("Прошу взыскать 150 000 рублей.", PREVIOUS)
        assert len(sections) == 1
        assert sections[0]["text"] == "Прошу взыскать 150 000 рублей."
        assert sections[0]["citations"] == []
        assert sections[0]["needs_review"] is True

    def test_empty_text_gives_nothing(self) -> None:
        assert resplit_sections("   \n  ", PREVIOUS) == []

    def test_no_previous_sections(self) -> None:
        """Правка без сформированного проекта: текст всё равно виден."""
        sections = resplit_sections("Правка судьи.", None)
        assert len(sections) == 1
        assert sections[0]["needs_review"] is True


class TestHeadingMatching:
    def test_lowercase_heading(self) -> None:
        """Человек, правивший текст, мог набрать заголовок строчными."""
        sections = resplit_sections(
            "решил\n\nВзыскать 150 000 руб.", PREVIOUS
        )
        operative = next(s for s in sections if s["key"] == "operative")
        assert operative["text"] == "Взыскать 150 000 руб."

    def test_heading_inside_line_not_a_heading(self) -> None:
        """«УСТАНОВИЛ, ЧТО» — не заголовок раздела."""
        sections = resplit_sections(
            "РЕШИЛ\n\nУСТАНОВИЛ, ЧТО иск подлежит удовлетворению.",
            PREVIOUS,
        )
        operative = next(s for s in sections if s["key"] == "operative")
        assert operative["text"] == "УСТАНОВИЛ, ЧТО иск подлежит удовлетворению."

    def test_broken_previous_format(self) -> None:
        """Раньше в поле разделов лежал и список строк, и словари."""
        assert resplit_sections("текст", ["01_claim.txt"]) [0]["needs_review"] is True
