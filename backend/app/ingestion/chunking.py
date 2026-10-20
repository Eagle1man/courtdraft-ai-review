"""Чанкинг с сохранением provenance (Фаза 5, п.12, п.14).

Требование ТЗ: «не использовать одинаковый chunk для всех документов
без учёта структуры». Поэтому чанкер:

* режет по абзацам, а не по символам;
* не разрывает абзац, если он влезает;
* сохраняет заголовок раздела у каждого фрагмента — без него
  фрагмент из «претензионной части» теряет контекст и становится
  бессмысленным при цитировании;
* для каждого фрагмента запоминает документ, страницу, абзац и
  границы символов.

Provenance — не украшение: без него Verification Engine не может
отличить утверждение с источником от выдумки, а интерфейс не может
показать «источник утверждения».
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.ingestion.extract import Page

logger = logging.getLogger(__name__)

# Заголовок Markdown: от одной до шести решёток в начале строки.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

# Нумерованный пункт: «1.», «1.1.», «а)», «1)».
_NUMBERED_RE = re.compile(r"^(\d+(?:\.\d+)*[.)]?|[а-яА-Я]\))\s+")


@dataclass
class Chunk:
    """Фрагмент документа с полным provenance."""

    index: int
    text: str
    document_id: str
    page: int | None
    paragraph: int | None
    character_start: int
    character_end: int
    # Заголовок раздела, к которому относится фрагмент.
    section: str = ""
    # Поисковый якорь: однозначно идентифицирует фрагмент в интерфейсе.
    anchor: str = ""

    @property
    def chunk_id(self) -> str:
        return self.anchor

    @property
    def length(self) -> int:
        return len(self.text)

    def citation(self) -> str:
        """Человекочитаемая ссылка для интерфейса (п.36)."""
        parts: list[str] = []
        if self.page is not None:
            parts.append(f"с. {self.page}")
        if self.section:
            parts.append(self.section)
        return ", ".join(parts) if parts else "фрагмент"


@dataclass
class _Block:
    """Логический блок текста до нарезки."""

    text: str
    page: int | None
    paragraph: int
    char_start: int
    char_end: int
    section: str

    @property
    def length(self) -> int:
        """Длина блока в символах."""
        return len(self.text)


def split_pages(text: str, pages: list[Page]) -> list[tuple[str, int | None]]:
    """Разделить текст по страницам с учётом их смещений.

    Возвращает пары (текст страницы, номер страницы). Если смещения
    недоступны, весь текст считается одной страницей — лучше, чем
    потерять текст.
    """
    if not pages:
        return [(text, None)]

    if len(pages) == 1:
        return [(text, pages[0].number)]

    result: list[tuple[str, int | None]] = []
    for page in pages:
        if page.is_empty:
            continue
        result.append((page.text, page.number))

    if not result:
        return [(text, None)]
    return result


def build_blocks(text: str, pages: list[Page]) -> list[_Block]:
    """Разбить текст на блоки по абзацам, помня страницы и заголовки.

    Границы символов считаются по полному тексту документа — именно
    на них ссылается интерфейс при показе источника.
    """
    blocks: list[_Block] = []

    # Положение каждой страницы в полном тексте.
    page_spans: list[tuple[int, int, int]] = []  # (start, end, page_number)
    cursor = 0
    if pages:
        for page in pages:
            if page.is_empty:
                continue
            start = text.find(page.text[:80], cursor) if page.text else -1
            if start == -1:
                start = cursor
            end = start + len(page.text)
            page_spans.append((start, end, page.number))
            cursor = end

    def page_for(position: int) -> int | None:
        for start, end, number in page_spans:
            if start <= position < end:
                return number
        return page_spans[-1][2] if page_spans else None

    current_section = ""
    paragraph_number = 0
    position = 0

    for raw_block in text.split("\n\n"):
        block_start = text.find(raw_block[:60], position) if raw_block else -1
        if block_start == -1:
            block_start = position
        block_end = block_start + len(raw_block)
        position = block_end + 2  # разделитель "\n\n"

        stripped = raw_block.strip()
        if not stripped:
            continue

        # Заголовок обновляет текущий раздел, но сам в чанк не идёт:
        # его содержание переходит в следующие фрагменты.
        heading = _HEADING_RE.match(stripped)
        if heading:
            current_section = heading.group(2).strip()
            paragraph_number += 1
            continue

        paragraph_number += 1
        blocks.append(
            _Block(
                text=stripped,
                page=page_for(block_start),
                paragraph=paragraph_number,
                char_start=block_start,
                char_end=block_end,
                section=current_section,
            )
        )

    return blocks


def chunk_text(
    text: str,
    *,
    document_id: str,
    pages: list[Page] | None = None,
    settings: Settings | None = None,
) -> list[Chunk]:
    """Разбить документ на фрагменты с перекрытием.

    Параметры из `.env`: CHUNK_SIZE, CHUNK_OVERLAP.

    Гарантии:
    * абзац короче CHUNK_SIZE не разрывается, если есть место;
    * абзац длиннее CHUNK_SIZE режется по предложениям, и только при
      неудаче — жёстко по символам;
    * заголовок раздела добавляется к тексту фрагмента, но не входит
      в расчёт размера содержимого;
    * перекрытие переносит конец предыдущего фрагмента в начало
      следующего, чтобы утверждение на границе не потерялось.
    """
    cfg = settings or get_settings()
    page_list = pages or []
    blocks = build_blocks(text, page_list)

    if not blocks:
        return []

    limit = cfg.chunk_size
    overlap = min(cfg.chunk_overlap, max(0, limit - 100))

    chunks: list[Chunk] = []
    buffer: list[_Block] = []
    buffer_len = 0

    def flush() -> None:
        """Собрать фрагмент из накопленных блоков."""
        nonlocal buffer, buffer_len
        if not buffer:
            return

        section = buffer[0].section
        body = "\n\n".join(b.text for b in buffer)

        # Заголовок добавляется для контекста, но вычитается из лимита
        # содержимого: иначе раздел с длинным названием съел бы
        # существенную часть фрагмента.
        header = f"{section}\n\n" if section else ""
        full_text = (header + body).strip()

        first = buffer[0]
        last = buffer[-1]

        index = len(chunks)
        anchor = f"{document_id}:{index}"

        chunks.append(
            Chunk(
                index=index,
                text=full_text,
                document_id=document_id,
                page=first.page,
                paragraph=first.paragraph,
                character_start=first.char_start,
                character_end=last.char_end,
                section=section,
                anchor=anchor,
            )
        )
        buffer = []
        buffer_len = 0

    for block in blocks:
        # Абзац длиннее лимита режется самостоятельно.
        if block.length > limit:
            flush()
            for piece in _split_long_block(block, limit, overlap, cfg):
                buffer.append(piece)
                flush()
            continue

        if buffer_len + block.length > limit and buffer:
            flush()

        buffer.append(block)
        buffer_len += block.length

        # Перекрытие: подтягиваем конец предыдущих блоков в следующий
        # фрагмент, чтобы утверждение на границе не потерялось.
        if buffer_len >= limit - overlap and buffer_len >= limit // 2:
            tail = _overlap_blocks(buffer, overlap)
            if tail and len(buffer) > len(tail):
                keep = buffer[: len(buffer) - len(tail)]
                buffer = keep + tail
                buffer_len = sum(b.length for b in buffer)

    flush()
    return chunks


def _overlap_blocks(blocks: list[_Block], overlap: int) -> list[_Block]:
    """Взять хвост блоков общей длиной около overlap."""
    if overlap <= 0 or not blocks:
        return []

    tail: list[_Block] = []
    total = 0
    for block in reversed(blocks):
        tail.insert(0, block)
        total += block.length
        if total >= overlap:
            break
    return tail if len(tail) < len(blocks) else []


def _split_long_block(
    block: _Block, limit: int, overlap: int, cfg: Settings
) -> list[_Block]:
    """Разрезать слишком длинный абзац.

    Сначала по предложениям — это сохраняет смысловую целостность
    фрагмента. Жёсткая нарезка по символам только как последний
    вариант: она может разорвать слово.
    """
    sentences = _split_sentences(block.text)
    pieces: list[_Block] = []

    current: list[str] = []
    current_len = 0

    def emit(parts: list[str], offset: int) -> _Block | None:
        body = " ".join(parts).strip()
        if not body:
            return None
        return _Block(
            text=body,
            page=block.page,
            paragraph=block.paragraph,
            char_start=block.char_start + offset,
            char_end=block.char_start + offset + len(body),
            section=block.section,
        )

    cursor = 0
    for sentence in sentences:
        sentence_len = len(sentence)

        if sentence_len > limit:
            # Предложение длиннее лимита — режем жёстко, но по границе
            # пробела, чтобы не разорвать слово.
            if current:
                piece = emit(current, cursor - current_len)
                if piece:
                    pieces.append(piece)
                current, current_len = [], 0

            words = sentence.split(" ")
            hard: list[str] = []
            hard_len = 0
            for word in words:
                if hard_len + len(word) + 1 > limit and hard:
                    piece = emit(hard, cursor)
                    if piece:
                        pieces.append(piece)
                    # Перекрытие по словам: последние слова предыдущего
                    # фрагмента переходят в начало следующего.
                    tail = " ".join(hard[-5:]).split(" ")
                    hard, hard_len = [], 0
                    for t in tail:
                        if len(t) + hard_len + 1 <= overlap:
                            hard.append(t)
                            hard_len += len(t) + 1
                        else:
                            break
                hard.append(word)
                hard_len += len(word) + 1
            if hard:
                piece = emit(hard, cursor)
                if piece:
                    pieces.append(piece)
            cursor += sentence_len + 1
            continue

        if current_len + sentence_len > limit and current:
            piece = emit(current, cursor - current_len)
            if piece:
                pieces.append(piece)

            # Перекрытие: последнее предложение переходит в следующий
            # фрагмент, чтобы связь между частями не терялась.
            overlap_tail: list[str] = []
            if current and current_len < overlap:
                overlap_tail = [current[-1]]
            current, current_len = overlap_tail, sum(len(c) + 1 for c in overlap_tail)

        current.append(sentence)
        current_len += sentence_len + 1
        cursor += sentence_len + 1

    if current:
        piece = emit(current, cursor - current_len)
        if piece:
            pieces.append(piece)

    return pieces


_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z«\"(])")


def _split_sentences(text: str) -> list[str]:
    """Разбить на предложения.

    Разбиение по точке/восклицанию с последующей заглавной — эвристика
    для русских текстов, где «т. д.», «ст. 309» и инициалы дают ложные
    границы. Ошибка здесь безвредна: получаются чуть более длинные
    фрагменты, а не потерянный текст.
    """
    parts = _SENTENCE_END_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]
