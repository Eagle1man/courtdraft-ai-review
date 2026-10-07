"""Тесты векторного хранилища и поиска (Фаза 4, п.25).

Работают на встроенном Qdrant (`:memory:`) — сервер на ноутбуке 8 GB
не поднять. Тот же код принимает и серверный режим через QDRANT_MODE.
"""

from __future__ import annotations

import math

import pytest

from app.embeddings.base import Embedding
from app.embeddings.mock import MockEmbeddingProvider
from app.rag.retrieval import (
    BM25Index,
    Document,
    Retriever,
    build_document_from_embedding,
    reciprocal_rank_fusion,
    tokenize,
)
from app.rag.store import (
    CollectionName,
    SearchFilters,
    VectorStore,
    _point_id,
    build_filter,
)

DIM = 64


@pytest.fixture
def store() -> VectorStore:
    return make_store()


def make_store() -> VectorStore:
    """Встроенный Qdrant: сервер на ноутбуке 8 GB не поднять."""
    from qdrant_client import QdrantClient

    return VectorStore(QdrantClient(":memory:"), dimension=DIM)


def make_embedding(
    chunk_id: str,
    text: str,
    *,
    document_id: str = "doc-1",
    document_type: str = "CLAIM",
    page: int = 1,
) -> Embedding:
    return Embedding(
        vector=[],
        chunk_id=chunk_id,
        document_id=document_id,
        filename="doc.pdf",
        document_type=document_type,
        page=page,
        paragraph=1,
        text=text,
    )


class TestTokenize:
    def test_lowercases_and_strips_stopwords(self) -> None:
        tokens = tokenize("Оплата была произведена в полном объеме")
        assert "оплата" in tokens
        assert "произведена" in tokens
        # «в» и «была» — стоп-слова
        assert "в" not in tokens
        assert "была" not in tokens

    def test_keeps_numbers(self) -> None:
        """Номера статей и суммы — ключ к точному поиску в праве."""
        assert "309" in tokenize("статья 309 ГК")
        assert "150000" in tokenize("150000 рублей")

    def test_empty_input(self) -> None:
        assert tokenize("") == []
        assert tokenize("   ") == []


class TestBM25Index:
    def test_finds_exact_term(self) -> None:
        index = BM25Index()
        index.add(Document(chunk_id="c1", text="Оплата произведена по договору"))
        index.add(Document(chunk_id="c2", text="Договор заключён в мае"))

        hits = index.search("оплата")
        assert hits
        assert hits[0].chunk_id == "c1"

    def test_rare_term_outranks_common(self) -> None:
        """IDF: редкое слово должно весить больше частого."""
        index = BM25Index()
        for i in range(10):
            index.add(Document(chunk_id=f"common{i}", text="договор поставки"))
        index.add(Document(chunk_id="rare", text="неустойка за просрочку"))

        hits = index.search("неустойка")
        assert hits[0].chunk_id == "rare"

    def test_no_match_returns_empty(self) -> None:
        index = BM25Index()
        index.add(Document(chunk_id="c1", text="договор"))
        assert index.search("абвгд") == []

    def test_empty_index_returns_empty(self) -> None:
        assert BM25Index().search("договор") == []

    def test_filter_by_document_type(self) -> None:
        """Фильтрация по типу документа — требование п.25."""
        index = BM25Index()
        index.add(Document(chunk_id="claim", text="исковое заявление", document_type="CLAIM"))
        index.add(Document(chunk_id="prot", text="исковое заявление", document_type="PROTOCOL"))

        hits = index.search(
            "исковое заявление", filters=SearchFilters(document_type="PROTOCOL")
        )
        assert len(hits) == 1
        assert hits[0].chunk_id == "prot"

    def test_filter_by_case_id(self) -> None:
        index = BM25Index()
        index.add(Document(chunk_id="a", text="факт", case_id="case-1"))
        index.add(Document(chunk_id="b", text="факт", case_id="case-2"))

        hits = index.search("факт", filters=SearchFilters(case_id="case-2"))
        assert [h.chunk_id for h in hits] == ["b"]

    def test_deterministic_order(self) -> None:
        """Одинаковый вход должен давать одинаковый порядок."""
        index = BM25Index()
        for i in range(5):
            index.add(Document(chunk_id=f"c{i}", text="одинаковый текст"))

        first = [h.chunk_id for h in index.search("одинаковый")]
        second = [h.chunk_id for h in index.search("одинаковый")]
        assert first == second

    def test_bm25_formula_positive_scores(self) -> None:
        index = BM25Index()
        index.add(Document(chunk_id="c1", text="платеж"))
        hits = index.search("платеж")
        assert hits[0].score > 0


class TestReciprocalRankFusion:
    def _results(self, ids: list[str]) -> list:
        from app.rag.store import SearchResult

        return [
            SearchResult(
                embedding=Embedding(vector=[], chunk_id=i, document_id="d", text=i),
                score=1.0,
                collection="t",
            )
            for i in ids
        ]

    def test_merges_two_listings(self) -> None:
        fused = reciprocal_rank_fusion(
            [self._results(["a", "b", "c"]), self._results(["c", "a", "d"])],
            k=60,
        )
        ids = [f.chunk_id for f in fused]
        # a и c есть в обоих списках -> должны подняться выше b и d
        assert set(ids) == {"a", "b", "c", "d"}
        assert ids.index("a") < ids.index("b")

    def test_empty_input(self) -> None:
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[], []]) == []

    def test_respects_limit(self) -> None:
        fused = reciprocal_rank_fusion([self._results(["a", "b", "c", "d"])], limit=2)
        assert len(fused) == 2

    def test_formula_value(self) -> None:
        """Проверка самой формулы, а не только порядка."""
        fused = reciprocal_rank_fusion([self._results(["a"])], k=60)
        # rank 0 -> 1/(60+0+1)
        assert math.isclose(fused[0].score, 1 / 61)

    def test_skips_results_without_id(self) -> None:
        from app.rag.store import SearchResult

        broken = [
            SearchResult(
                embedding=Embedding(vector=[], chunk_id="", document_id="d", text=""),
                score=1.0,
                collection="t",
            )
        ]
        fused = reciprocal_rank_fusion([broken], k=60)
        assert fused == []


class TestPointId:
    def test_uuid_passthrough(self) -> None:
        uid = "12345678-1234-5678-1234-567812345678"
        assert _point_id(uid) == uid

    def test_deterministic_for_arbitrary_string(self) -> None:
        """Один chunk_id всегда даёт один id: иначе переиндексация
        создавала бы дубли."""
        first = _point_id("case-1:chunk-5")
        second = _point_id("case-1:chunk-5")
        assert first == second
        assert first != _point_id("case-1:chunk-6")


class TestVectorStore:
    async def test_ensure_collection_is_idempotent(self) -> None:
        store = make_store()
        assert store.ensure_collection(CollectionName.DOCUMENTS.value) is True
        assert store.ensure_collection(CollectionName.DOCUMENTS.value) is True

    async def test_upsert_and_search(self) -> None:
        store = make_store()
        embeddings_provider = MockEmbeddingProvider(dimension=DIM)
        texts = ["Оплата произведена по договору", "Ответчик не явился в суд"]
        vectors = await embeddings_provider.embed(texts)

        embs = [
            Embedding(
                vector=vectors[i],
                chunk_id=f"case-1:{i}",
                document_id="doc-1",
                document_type="CLAIM",
                text=texts[i],
            )
            for i in range(2)
        ]
        assert store.upsert(CollectionName.DOCUMENTS.value, embs) == 2

        results = store.search(CollectionName.DOCUMENTS.value, vectors[0], limit=5)
        assert results
        assert results[0].embedding.chunk_id == "case-1:0"

    async def test_upsert_is_idempotent(self) -> None:
        store = make_store()
        provider = MockEmbeddingProvider(dimension=DIM)
        vector = (await provider.embed(["текст"]))[0]
        emb = Embedding(vector=vector, chunk_id="case-1:0", document_id="d", text="текст")

        store.upsert(CollectionName.DOCUMENTS.value, [emb])
        store.upsert(CollectionName.DOCUMENTS.value, [emb])
        stats = store.stats(CollectionName.DOCUMENTS.value)
        assert stats.points == 1

    async def test_empty_upsert_returns_zero(self) -> None:
        assert make_store().upsert(CollectionName.DOCUMENTS.value, []) == 0

    async def test_search_filters_by_case(self) -> None:
        """Ключевая изоляция: поиск по делу не должен видеть чужие фрагменты."""
        store = make_store()
        provider = MockEmbeddingProvider(dimension=DIM)
        v1 = (await provider.embed(["договор"]))[0]
        v2 = (await provider.embed(["договор"]))[0]

        store.upsert(
            CollectionName.DOCUMENTS.value,
            [
                Embedding(vector=v1, chunk_id="case-1:0", document_id="d1", text="договор"),
                Embedding(vector=v2, chunk_id="case-2:0", document_id="d2", text="договор"),
            ],
        )

        found = store.search(
            CollectionName.DOCUMENTS.value, v1, limit=10, filters=SearchFilters(case_id="case-1")
        )
        assert len(found) == 1
        assert found[0].embedding.chunk_id == "case-1:0"

    async def test_delete_by_case(self) -> None:
        store = make_store()
        provider = MockEmbeddingProvider(dimension=DIM)
        vector = (await provider.embed(["текст"]))[0]

        store.upsert(
            CollectionName.DOCUMENTS.value,
            [
                Embedding(vector=vector, chunk_id="case-1:0", document_id="d", text="текст"),
                Embedding(vector=vector, chunk_id="case-2:0", document_id="d", text="текст"),
            ],
        )
        store.delete_by_case(CollectionName.DOCUMENTS.value, "case-1")

        stats = store.stats(CollectionName.DOCUMENTS.value)
        assert stats.points == 1

    async def test_stats_for_missing_collection(self) -> None:
        stats = make_store().stats("нет_такой")
        assert stats.exists is False

    def test_health_on_embedded(self) -> None:
        assert make_store().health() is True

    def test_embedded_flag(self) -> None:
        assert make_store().is_embedded is True

    async def test_provenance_survives_roundtrip(self) -> None:
        """Provenance (п.12) обязан пережить запись и поиск —
        без него нельзя показать источник утверждения."""
        store = make_store()
        provider = MockEmbeddingProvider(dimension=DIM)
        vector = (await provider.embed(["факт"]))[0]

        store.upsert(
            CollectionName.DOCUMENTS.value,
            [
                Embedding(
                    vector=vector,
                    chunk_id="case-1:0",
                    document_id="doc-x",
                    filename="05_protocol.pdf",
                    document_type="PROTOCOL",
                    page=7,
                    paragraph=3,
                    character_start=100,
                    character_end=250,
                    text="Ответчик возражает против исковых требований",
                )
            ],
        )

        hits = store.search(CollectionName.DOCUMENTS.value, vector, limit=1)
        emb = hits[0].embedding
        assert emb.page == 7
        assert emb.paragraph == 3
        assert emb.character_start == 100
        assert emb.filename == "05_protocol.pdf"
        assert emb.document_type == "PROTOCOL"


class TestBuildFilter:
    def test_none_returns_none(self) -> None:
        assert build_filter(None) is None

    def test_empty_filters_return_none(self) -> None:
        assert build_filter(SearchFilters()) is None

    def test_case_id_filter(self) -> None:
        f = build_filter(SearchFilters(case_id="c1"))
        assert f is not None
        assert len(f.must) == 1

    def test_effective_date_produces_range_and_must_not(self) -> None:
        """п.16: нужна редакция, действовавшая на дату, — это
        effective_from <= дата И НЕ effective_to < дата."""
        from datetime import date

        f = build_filter(SearchFilters(effective_on=date(2020, 5, 1)))
        assert f is not None
        assert len(f.must) == 1
        assert len(f.must_not) == 1

    def test_multiple_filters_combined(self) -> None:
        f = build_filter(SearchFilters(case_id="c1", document_type="CLAIM", court="Суд"))
        assert f is not None
        assert len(f.must) == 3


class TestRetriever:
    async def _seeded(self, retriever: Retriever, store: VectorStore) -> None:
        provider = MockEmbeddingProvider(dimension=DIM)
        texts = [
            "Договор был заключён 15 мая 2019 года",
            "Оплата по договору произведена в полном объёме",
            "Ответчик в судебное заседание не явился",
        ]
        vectors = await provider.embed(texts)
        embs = [
            Embedding(
                vector=vectors[i],
                chunk_id=f"case-1:{i}",
                document_id="doc-1",
                document_type="CLAIM",
                text=text,
            )
            for i, text in enumerate(texts)
        ]
        store.upsert(CollectionName.DOCUMENTS.value, embs)
        retriever.index_for_bm25(
            [
                build_document_from_embedding(e, case_id="case-1")
                for e in embs
            ]
        )

    async def test_uses_rrf_when_both_sources(self) -> None:
        store = make_store()
        retriever = Retriever(store, MockEmbeddingProvider(dimension=DIM))
        await self._seeded(retriever, store)

        result = await retriever.search("договор заключён")
        assert result.method == "rrf"
        assert result.dense_count > 0
        assert result.sparse_count > 0
        assert len(result.results) > 0

    async def test_bm25_only_when_nothing_indexed(self) -> None:
        store = make_store()
        retriever = Retriever(store, MockEmbeddingProvider(dimension=DIM))
        result = await retriever.search("что угодно")
        assert result.method == "none"
        assert result.results == []

    async def test_respects_limit(self) -> None:
        store = make_store()
        retriever = Retriever(store, MockEmbeddingProvider(dimension=DIM))
        await self._seeded(retriever, store)

        result = await retriever.search("договор", limit=1)
        assert len(result.results) == 1

    async def test_filters_applied(self) -> None:
        store = make_store()
        retriever = Retriever(store, MockEmbeddingProvider(dimension=DIM))
        await self._seeded(retriever, store)

        result = await retriever.search(
            "договор", filters=SearchFilters(case_id="чужое-дело")
        )
        assert result.results == []

    async def test_empty_query_does_not_crash(self) -> None:
        store = make_store()
        retriever = Retriever(store, MockEmbeddingProvider(dimension=DIM))
        await self._seeded(retriever, store)
        result = await retriever.search("")
        assert result is not None


class TestRetrievalQuality:
    """Метрики из п.63 на детерминированном корпусе.

    Считаются на MOCK-эмбеддингах: детерминизм гарантирует, что
    измеряется работа конвейера, а не случайность модели.
    """

    CORPUS = [
        ("c0", "Договор поставки заключён 15 мая 2019 года между истцом и ответчиком"),
        ("c1", "Оплата по договору произведена в полном объёме, подтверждается чеком"),
        ("c2", "Ответчик в судебное заседание не явился, уважительных причин не сообщил"),
        ("c3", "Размер ущерба определён заключением эксперта в сумме 150000 рублей"),
        ("c4", "Истец требовал взыскания неустойки за просрочку исполнения обязательства"),
    ]

    def _retriever(self) -> Retriever:
        store = make_store()
        retriever = Retriever(store, MockEmbeddingProvider(dimension=DIM))
        docs = [
            Document(chunk_id=cid, text=text, case_id="case-1", document_type="CLAIM")
            for cid, text in self.CORPUS
        ]
        retriever.index_for_bm25(docs)
        return retriever

    async def test_recall_at_5(self) -> None:
        """Поиск оплаты должен находить фрагмент про оплату в топ-5."""
        retriever = self._retriever()
        result = await retriever.search("произведена ли оплата по договору", limit=5)
        found = {r.chunk_id for r in result.results}
        assert "c1" in found

    async def test_mrr_positive_for_exact_topic(self) -> None:
        """MRR должен быть > 0: релевантный фрагмент где-то находится."""
        retriever = self._retriever()
        result = await retriever.search("заключение эксперта о размере ущерба", limit=5)
        ids = [r.chunk_id for r in result.results]
        assert ids, "поиск ничего не нашёл"

        relevant = {"c3"}
        rr = 0.0
        for position, chunk_id in enumerate(ids, start=1):
            if chunk_id in relevant:
                rr = 1.0 / position
                break
        assert rr > 0

    async def test_two_queries_return_stable_results(self) -> None:
        """Воспроизводимость: без неё метрики измеряли бы шум."""
        retriever = self._retriever()
        first = await retriever.search("неявка ответчика в суд", limit=5)
        second = await retriever.search("неявка ответчика в суд", limit=5)
        assert [r.chunk_id for r in first.results] == [
            r.chunk_id for r in second.results
        ]
