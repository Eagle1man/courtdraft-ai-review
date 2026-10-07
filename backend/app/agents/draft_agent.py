"""Draft Agent: формирование проекта судебного акта (Фаза 9, ТЗ п.27).

Ключевое решение: разделы генерируются ПО ОТДЕЛЬНО, а не одним длинным
запросом.

Почему: модель на 1.5B параметров, работающая на CPU, на длинном
запросе начинает «плыть» — теряет структуру, повторяется, дорисовывает
факты. Короткий запрос с чёткой инструкцией на один раздел даёт
заметно лучший результат и предсказуемое время.

Второе правило, жёстче: модель НЕ выдумывает числа. Все суммы,
даты и номера берутся из пакета доказательств и подставляются в текст
механически. Если числа нет в пакете — раздел получает пометку
о необходимости проверки.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.agents.evidence_pack import EvidencePack
from app.config import Settings, get_settings
from app.llm import build_llm_provider
from app.llm.base import LLMMessage, LLMProvider, LLMRequest, LLMRole

logger = logging.getLogger(__name__)

# Пометка, которую ТЗ требует вместо выдумки (п.23, п.27).
NEEDS_REVIEW = "ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ"
NO_LAW_FOUND = "Норма права не найдена. Требуется проверка специалистом."

SYSTEM_PROMPT = """Ты — помощник судьи. Пишешь ТОЛЬКО текст одного раздела решения суда.

ПРАВИЛА:
1. Начинай сразу с текста раздела. Никаких заголовков, подзаголовков, нумерации.
2. НИКОГДА не повторяй подписи служебных блоков
   («СВЕДЕНИЯ О ДЕЛЕ», «МАТЕРИАЛЫ ДЕЛА», «СУММЫ», «ДАТЫ», «ИНСТРУКЦИЯ»).
   Это метки для тебя, а не текст для суда.
3. Не выдумывай факты, суммы, даты и номера. Бери только из материала.
4. Если сведений не хватает — напиши "{review}".
5. Если подходящей нормы права в материале нет — напиши "{no_law}".
6. Пиши по-русски, в официально-деловом стиле, короткими предложениями."""


@dataclass
class SectionDraft:
    """Сгенерированный раздел проекта."""

    key: str
    name: str
    text: str
    # Отметка, получен ли текст от настоящей модели или заглушки.
    is_mock: bool = True
    citations: list[str] = field(default_factory=list)
    needs_review: bool = False
    latency_ms: int = 0
    error: str = ""


@dataclass
class DraftResult:
    """Проект судебного акта целиком."""

    case_number: str
    sections: list[SectionDraft] = field(default_factory=list)
    model: str = ""
    provider: str = ""
    total_latency_ms: int = 0

    @property
    def text(self) -> str:
        """Собрать полный текст проекта по шаблону."""
        parts: list[str] = []
        for section in self.sections:
            parts.append(f"{section.name.upper()}\n\n{section.text}")
        return "\n\n".join(parts)

    @property
    def sections_needing_review(self) -> list[SectionDraft]:
        return [s for s in self.sections if s.needs_review]

    def sources(self) -> list[str]:
        out: list[str] = []
        for section in self.sections:
            for citation in section.citations:
                if citation not in out:
                    out.append(citation)
        return out

    def stats(self) -> dict[str, int]:
        return {
            "sections": len(self.sections),
            "sections_needing_review": len(self.sections_needing_review),
            "characters": len(self.text),
            "citations": len(self.sources()),
        }


def _format_amounts(pack: EvidencePack) -> str:
    if not pack.amounts:
        return f"суммы в материалах не указаны — укажи {NEEDS_REVIEW}"
    return "суммы, встречающиеся в материалах (руб.): " + ", ".join(pack.amounts[:10])


def _format_participants(pack: EvidencePack) -> str:
    if not pack.participants:
        return "участники в материалах не указаны"
    return "; ".join(pack.participants)


def build_section_prompt(
    section: dict[str, Any],
    pack: EvidencePack,
) -> tuple[str, list[str]]:
    """Собрать запрос на один раздел.

    Возвращает (текст запроса, ссылки-источники, использованные в разделе).
    """
    categories: list[str] = section.get("evidence_categories", [])
    name = section["name"]
    purpose = section.get("purpose", "")
    hint = section.get("prompt_hint", "")

    evidence_blocks: list[str] = []
    citations: list[str] = []

    for category in categories:
        block = pack.text_for(category, limit=6)
        if block:
            evidence_blocks.append(f"[{category}]\n{block}")
            for item in pack.by_category(category)[:6]:
                if item.citation not in citations:
                    citations.append(item.citation)

    if pack.gaps:
        evidence_blocks.append(
            "[пробелы в материалах]\n" + "\n".join(f"- {gap}" for gap in pack.gaps)
        )

    if not evidence_blocks:
        evidence_blocks.append(
            "[материалы по этому разделу отсутствуют — раздел требует проверки специалистом]"
        )

    # Промпт намеренно компактный и без громоздких подписанных блоков.
    # Модель на 1.5B копирует в ответ всё, что выглядит как содержимое,
    # и служебные подписи предыдущей версии попадали прямо в проект.
    facts = (
        f"Дело № {pack.case_number}. Суд: {pack.court_name}. "
        f"Категория: {pack.category}. "
        f"Участники: {_format_participants(pack)}. "
        f"{_format_amounts(pack)}. "
        f"Даты: {'; '.join(pack.dates[:8]) or 'не указаны'}."
    )

    request = f"""Напиши раздел «{name}» решения суда.

Назначение раздела: {purpose}
{hint}

Сведения о деле: {facts}

Материалы:
{chr(10).join(evidence_blocks)}

Сейчас пиши текст раздела «{name}». Не повторяй названия блоков.
Если сведений не хватает — напиши: {NEEDS_REVIEW}
Если нормы права в материале нет — напиши: {NO_LAW_FOUND}"""

    return request, citations


def _postprocess(text: str, section: dict[str, Any]) -> tuple[str, bool]:
    """Почистить ответ модели.

    Модель часто повторяет заголовок раздела или добавляет нумерацию —
    это ломает структуру проекта.
    """
    name = section["name"].upper()
    needs_review = False

    cleaned = text.strip()

    # Убираем повторный заголовок в начале.
    lines = cleaned.split("\n")
    while lines and (not lines[0].strip() or name in lines[0].upper()[:20]):
        if lines and name not in lines[0].upper()[:20]:
            break
        lines.pop(0)
    cleaned = "\n".join(lines).strip()

    # Убираем служебные префиксы. Модель часто начинает раздел с
    # «Резолютивная часть:» или «Раздел 3:» — это ломает структуру
    # итогового документа, где раздел уже назван заголовком.
    cleaned = re.sub(
        r"^\s*(раздел\s*\d*\s*[:—-]?\s*|текст\s*[:—-]|ответ\s*[:—-]|"
        r"[а-яё]{3,20}\s+часть\s*[:—-]?)\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    if NEEDS_REVIEW in cleaned:
        needs_review = True
    lowered = cleaned.lower()
    if "не хватает" in lowered or "недостаточно данных" in lowered:
        needs_review = True
    if NO_LAW_FOUND.split(".")[0] in cleaned:
        needs_review = True

    # Горизонтальные разделители — оформление ответа модели, в тексте
    # проекта они не нужны: разделы разделяются заголовками.
    cleaned = re.sub(r"^\s*(?:-{3,}|_{3,}|\*{3,})\s*$", "", cleaned, flags=re.MULTILINE)

    # Убираем markdown-заголовки: модель оформляет раздел как
    # «### Описательная часть», а в проекте акта раздел уже назван
    # заголовком выше по тексту.
    lines = [
        ln for ln in cleaned.split("\n")
        if not re.match(r"^\s*#{1,6}\s", ln)
    ]
    cleaned = "\n".join(lines).strip()

    # Жирное выделение — это разметка ответа модели, а не текст документа.
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"__(.+?)__", r"\1", cleaned, flags=re.DOTALL)

    if not cleaned:
        needs_review = True
        cleaned = f"Материалы дела не позволяют подготовить раздел. {NEEDS_REVIEW}"

    cleaned = _drop_repeats(cleaned)

    return cleaned, needs_review


def _drop_repeats(text: str) -> str:
    """Убрать повторяющиеся строки.

    Модель на 1.5B часто зацикливается и печатает одну и ту же фразу
    несколько раз подряд. В проекте судебного акта это выглядит как
    неисправность, хотя текст был получен корректно.
    """
    seen: set[str] = set()
    kept: list[str] = []

    for raw in text.split("\n"):
        key = re.sub(r"\W+", "", raw.lower())
        # Короткие строки не сравниваем: «1.» или «-» повторяются законно.
        if len(key) > 25:
            if key in seen:
                continue
            seen.add(key)
        kept.append(raw)

    return "\n".join(kept).strip()


async def generate_draft(
    pack: EvidencePack,
    template: dict[str, Any],
    *,
    provider: LLMProvider | None = None,
    settings: Settings | None = None,
    only_sections: list[str] | None = None,
) -> DraftResult:
    """Сгенерировать проект судебного акта по разделам."""
    cfg = settings or get_settings()
    llm = provider or build_llm_provider(cfg)

    sections_to_do = [
        s for s in template.get("sections", [])
        if only_sections is None or s["key"] in only_sections
    ]

    result = DraftResult(
        case_number=pack.case_number,
        provider=llm.name,
        model=getattr(llm, "_model", ""),
    )
    started = time.perf_counter()

    for section in sections_to_do:
        request_text, citations = build_section_prompt(section, pack)

        request = LLMRequest(
            messages=[
                LLMMessage(
                    role="system",
                    content=SYSTEM_PROMPT.format(
                        review=NEEDS_REVIEW, no_law=NO_LAW_FOUND
                    ),
                ),
                LLMMessage(role="user", content=request_text),
            ],
            role=LLMRole.GENERATION,
            # Низкая температура: нужна работа с фактами, а не свободное письмо.
            temperature=0.1,
            # Раздел решения — не кандидатская, длинный текст роняет
            # качество на маленькой модели и растягивает время на CPU.
            # 420 токенов — предел для 1.5B на CPU: дальше качество
            # падает быстрее, чем растёт время генерации.
            max_tokens=420,
        )

        started_section = time.perf_counter()
        try:
            response = await llm.generate(request)
            text, needs_review = _postprocess(response.text, section)
            result.sections.append(
                SectionDraft(
                    key=section["key"],
                    name=section["name"],
                    text=text,
                    is_mock=response.is_mock,
                    citations=citations,
                    needs_review=needs_review,
                    latency_ms=int((time.perf_counter() - started_section) * 1000),
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Раздел %s не сгенерирован: %s", section["key"], exc)
            result.sections.append(
                SectionDraft(
                    key=section["key"],
                    name=section["name"],
                    text=f"Раздел не подготовлен из-за ошибки модели. {NEEDS_REVIEW}",
                    needs_review=True,
                    error=str(exc)[:200],
                )
            )

    result.total_latency_ms = int((time.perf_counter() - started) * 1000)
    return result
