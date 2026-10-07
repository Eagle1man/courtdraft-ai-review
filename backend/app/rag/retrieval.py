"""Поиск по индексу (Фаза 4, п.25).

Dense retrieval + sparse/BM25 + фильтры по метаданным + RRF.

Почему так, а не только dense: в юридических документах решающую роль
играют точные совпадения — номера статей, даты, суммы, номера дел.
Dense-векторы такие совпадения теряют. BM25 их находит, а RRF объединяет
оба списка без ручной настройки весов.

RRF (Reciprocal Rank Fusion) формула: score(d) = Σ 1/(k + rank_i(d)),
k = RRF_K. Параметр k подобран так, чтобы вклад верхних позиций
преобладал, но глубокие результаты не исчезали совсем.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.config import Settings, get_settings
from app.embeddings.base import Embedding, EmbeddingProvider
from app.rag.store import CollectionName, SearchFilters, SearchResult, VectorStore

logger = logging.getLogger(__name__)

# Токены юридического текста: слова, числа, номера статей.
_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)

# Стоп-слова русского текста. Сокращённый список: полный убрал бы
# значимые для права слова («не», «лицо», «право»).
# Задано набором строк, а не списком: ruff --fix (SIM905) разворачивает
# многострочный .split() обратно в одну длинную строку.
_STOPWORD_TEXT = """
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы
по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг
ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя
ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без
будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой
совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех
никогда можно при наконец два об другой хоть после над больше тот через эти нас
про всего них какая много разве три эту моя впрочем хорошо свою этой перед
иногда лучше чуть том нельзя такой им более всегда конечно всю между это
"""

_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def tokenize(text: str) -> list[str]:
    """Разбить текст на токены для BM25."""
    return [
        token
        for token in _TOKEN_RE.findall((text or "").lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


@dataclass
class Document:
    """Документ локального индекса для BM25.

    Встроенный индекс нужен для MOCK-режима: поднимать сервер
    с полнотекстовым поиском на ноутбуке 8 GB нельзя, а проверять
    качество объединения поиска надо.
    """

    chunk_id: str
    text: str
    case_id: str = ""
    document_id: str = ""
    document_type: str = ""
    page: int | None = None
    filename: str = ""


class BM25Index:
    """Простой индексатор BM25 Okapi.

    Хранится в памяти и строится заново при каждом запуске процесса —
    на ноутбуке 8 GB держать постоянный индекс всех дел было бы
    неверно. В RUNTIME-режиме BM25 должен переехать в Qdrant
    (у него есть sparse-вектора) — это Фаза 4.2.
    """

    # Параметры Okapi: чем больше b, тем сильнее длина документа
    # влияет на нормировку. 1.2 — стандартное значение.
    _K1 = 1.5
    _B = 0.75

    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}
        self._tokens: dict[str, list[str]] = {}
        self._freqs: dict[str, Counter[str]] = {}
        self._df: Counter[str] = Counter()
        self._avg_len: float = 0.0

    def __len__(self) -> int:
        return len(self._docs)

    def add(self, document: Document) -> None:
        tokens = tokenize(document.text)
        self._docs[document.chunk_id] = document
        self._tokens[document.chunk_id] = tokens
        self._freqs[document.chunk_id] = Counter(tokens)
        for term in set(tokens):
            self._df[term] += 1
        self._recompute_avg_len()

    def add_many(self, documents: Sequence[Document]) -> None:
        for doc in documents:
            tokens = tokenize(doc.text)
            self._docs[doc.chunk_id] = doc
            self._tokens[doc.chunk_id] = tokens
            self._freqs[doc.chunk_id] = Counter(tokens)
            for term in set(tokens):
                self._df[term] += 1
        self._recompute_avg_len()

    def _recompute_avg_len(self) -> None:
        if not self._tokens:
            self._avg_len = 0.0
            return
        total = sum(len(t) for t in self._tokens.values())
        self._avg_len = total / len(self._tokens)

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: SearchFilters | None = None,
    ) -> list[SearchResult]:
        """Найти документы по формуле BM25."""
        query_terms = tokenize(query)
        if not query_terms or not self._docs:
            return []

        total_docs = len(self._docs)
        scored: list[tuple[str, float]] = []

        for chunk_id, tokens in self._tokens.items():
            doc = self._docs[chunk_id]
            if not self._matches_filters(doc, filters):
                continue

            freqs = self._freqs[chunk_id]
            doc_len = len(tokens)
            score = 0.0

            for term in query_terms:
                tf = freqs.get(term, 0)
                if tf == 0:
                    continue
                # IDF сглаживание: +1 в числителе и знаменателе, чтобы
                # не получить отрицательный вес для термина во всех доках.
                df = self._df.get(term, 0)
                idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
                norm = 1 - self._B + self._B * (doc_len / self._avg_len if self._avg_len else 1.0)
                score += idf * (tf * (self._K1 + 1)) / (tf + self._K1 * norm)

            if score <= 0:
                continue
            scored.append((chunk_id, score))

        # Сортировка по убыванию; при равенстве — по chunk_id, чтобы
        # результат был воспроизводимым между прогонами.
        scored.sort(key=lambda pair: (-pair[1], pair[0]))

        results: list[SearchResult] = []
        for chunk_id, score in scored[:limit]:
            doc = self._docs[chunk_id]
            results.append(
                SearchResult(
                    embedding=Embedding(
                        vector=[],
                        chunk_id=chunk_id,
                        document_id=doc.document_id,
                        filename=doc.filename,
                        document_type=doc.document_type,
                        page=doc.page,
                        text=doc.text,
                    ),
                    score=score,
                    collection="bm25",
                )
            )
        return results

    @staticmethod
    def _matches_filters(doc: Document, filters: SearchFilters | None) -> bool:
        """Фильтры BM25 — те же, что и у dense-поиска."""
        if filters is None:
            return True
        if filters.case_id and doc.case_id != filters.case_id:
            return False
        if filters.document_type and doc.document_type != filters.document_type:
            return False
        # noqa уже не нужен: условие читается как «если фильтр задан и не совпал».
        return not (filters.document_id and doc.document_id != filters.document_id)


@dataclass
class RetrievalResult:
    """Объединённый результат поиска."""

    results: list[SearchResult]
    dense_count: int
    sparse_count: int
    method: str

    def __len__(self) -> int:
        return len(self.results)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[SearchResult]],
    *,
    k: int = 60,
    limit: int = 10,
) -> list[SearchResult]:
    """Объединить несколько ранжирований через RRF.

    RRF объединяет списки по ЗВАНИЯМ (рангам), а не по сырым оценкам.
    Это принципиально: оценки dense и BM25 несопоставимы (косинус
    против TF-IDF), усреднять их бессмысленно. Ранги сопоставимы всегда.
    """
    if not rankings:
        return []

    fused: dict[str, SearchResult] = {}
    scores: dict[str, float] = {}
    contributions: dict[str, int] = {}

    for ranking in rankings:
        # Один chunk_id может встретиться в нескольких списках —
        # это и есть признак согласия двух методов.
        for rank, result in enumerate(ranking):
            cid = result.chunk_id
            if not cid:
                continue
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            contributions[cid] = contributions.get(cid, 0) + 1
            if cid not in fused:
                fused[cid] = result

    ordered = sorted(
        scores.items(),
        # При равенстве — по числу методов, затем по chunk_id
        # для воспроизводимости.
        key=lambda pair: (-pair[1], -contributions[pair[0]], pair[0]),
    )

    combined: list[SearchResult] = []
    for chunk_id, score in ordered[:limit]:
        result = fused[chunk_id]
        combined.append(
            SearchResult(
                embedding=result.embedding,
                score=score,
                collection=result.collection,
            )
        )
    return combined


class Retriever:
    """Поиск по делу: dense + BM25 + RRF."""

    def __init__(
        self,
        store: VectorStore,
        embeddings: EmbeddingProvider,
        settings: Settings | None = None,
    ) -> None:
        self._store = store
        self._embeddings = embeddings
        self._settings = settings or get_settings()
        self._bm25 = BM25Index()

    @property
    def bm25_size(self) -> int:
        return len(self._bm25)

    def index_for_bm25(self, documents: Sequence[Document]) -> None:
        """Проиндексировать документы для BM25."""
        self._bm25.add_many(documents)

    def reset_bm25(self) -> None:
        self._bm25 = BM25Index()

    async def search(
        self,
        query: str,
        *,
        collection: str = CollectionName.DOCUMENTS,
        limit: int | None = None,
        candidates: int | None = None,
        filters: SearchFilters | None = None,
    ) -> RetrievalResult:
        """Найти релевантные фрагменты.

        `candidates` фрагментов от каждого метода объединяются RRF в
        `limit` итоговых. Отдельный лимит кандидатов нужен, потому что
        RRF работает по рангам: обрезать каждый список до limit до
        слияния значило бы отбросить материал, который после слияния
        мог бы подняться.
        """
        top_k = limit or self._settings.retrieval_top_k
        top_n = candidates or self._settings.retrieval_candidates

        rankings: list[Sequence[SearchResult]] = []

        # Dense
        vectors = await self._embeddings.embed([query])
        dense = (
            self._store.search(collection, vectors[0], limit=top_n, filters=filters)
            if vectors
            else []
        )
        if dense:
            rankings.append(dense)

        # BM25
        sparse = self._bm25.search(query, limit=top_n, filters=filters)
        if sparse:
            rankings.append(sparse)

        if not rankings:
            return RetrievalResult(results=[], dense_count=0, sparse_count=0, method="none")

        method = "rrf" if len(rankings) > 1 else ("dense" if dense else "bm25")
        fused = reciprocal_rank_fusion(
            rankings, k=self._settings.rrf_k, limit=top_k
        )

        return RetrievalResult(
            results=fused,
            dense_count=len(dense),
            sparse_count=len(sparse),
            method=method,
        )


def build_document_from_embedding(emb: Embedding, *, case_id: str = "") -> Document:
    """Собрать документ локального индекса из эмбеддинга."""
    return Document(
        chunk_id=emb.chunk_id,
        text=emb.text,
        case_id=case_id or _extract_case_id(emb.chunk_id),
        document_id=emb.document_id,
        document_type=emb.document_type,
        page=emb.page,
        filename=emb.filename,
    )


def _extract_case_id(chunk_id: str) -> str:
    return chunk_id.split(":", 1)[0] if ":" in chunk_id else ""
