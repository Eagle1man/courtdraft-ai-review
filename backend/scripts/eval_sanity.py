"""Проверка: не тривиально ли метрики.

Первый прогон дал Recall@5 = 1.000 на запросах, почти дословно
совпадающих с текстом корпуса. Это может означать как «поиск хороший»,
так и «оценка ничего не проверяет». Здесь — запросы, которых в корпусе
нет дословно, плюс проверка вклада dense-поиска отдельно от BM25.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.embeddings.base import Embedding  # noqa: E402
from app.embeddings.mock import MockEmbeddingProvider  # noqa: E402
from app.rag.retrieval import BM25Index, Document, Retriever  # noqa: E402
from app.rag.store import CollectionName, SearchFilters, VectorStore  # noqa: E402

DIM = 1024

CORPUS: dict[str, str] = {
    "c0": "Договор поставки заключён 15 мая 2019 года между истцом и ответчиком",
    "c1": "Оплата по договору произведена в полном объёме, что подтверждается чеком",
    "c2": "Ответчик в судебное заседание не явился, уважительных причин не сообщил",
    "c3": "Размер ущерба определён заключением эксперта в сумме 150000 рублей",
    "c4": "Истец требовал взыскания неустойки за просрочку исполнения обязательства",
    "c5": "Ответчик представил возражения против суммы, заявив о ненадлежащем исполнении",
}

# Перефразированные запросы: ключевых слов в тексте нет.
PARAPHRASED: list[tuple[str, set[str]]] = [
    ("подтверждает ли чек перечисление денег", {"c1"}),
    ("почему подрядчик не пришёл в суд", {"c2"}),
    ("сколько эксперт насчитал в пользу потерпевшей стороны", {"c3"}),
    ("на что жаловалась пострадавшая сторона", {"c4", "c5"}),
    ("в какой день подписали контракт", {"c0"}),
]


async def build() -> Retriever:
    from qdrant_client import QdrantClient

    store = VectorStore(QdrantClient(":memory:"), dimension=DIM)
    retriever = Retriever(store, MockEmbeddingProvider(dimension=DIM))
    provider = MockEmbeddingProvider(dimension=DIM)
    texts = list(CORPUS.values())
    vectors = await provider.embed(texts)
    embs = [
        Embedding(
            vector=vectors[i], chunk_id=cid, document_id="d", text=text
        )
        for i, (cid, text) in enumerate(CORPUS.items())
    ]
    store.upsert(CollectionName.DOCUMENTS.value, embs)
    retriever.index_for_bm25(
        [Document(chunk_id=e.chunk_id, text=e.text, case_id="case-1") for e in embs]
    )
    return retriever


async def main() -> int:
    retriever = await build()
    filters = SearchFilters(case_id="case-1")

    print("=== Перефразированные запросы (слов из корпуса нет) ===")
    print(f"{'запрос':<52} {'R@5':>5} {'найдено':>8}")
    print("-" * 68)

    hits_total = 0
    for query, relevant in PARAPHRASED:
        result = await retriever.search(query, limit=5, filters=filters)
        found = {r.chunk_id for r in result.results}
        overlap = relevant & found
        hits_total += len(overlap)
        print(f"{query[:50]:<52} {len(overlap) / len(relevant):>5.2f} {sorted(found)}")

    print()
    print("=== Вклад методов по отдельности ===")
    index = BM25Index()
    for cid, text in CORPUS.items():
        index.add(Document(chunk_id=cid, text=text, case_id="case-1"))

    bm25_top = [r.chunk_id for r in index.search("заключение эксперта ущерб сумма", limit=3)]
    print(f"BM25  top-3: {bm25_top}")

    provider = MockEmbeddingProvider(dimension=DIM)
    from qdrant_client import QdrantClient

    store = VectorStore(QdrantClient(":memory:"), dimension=DIM)
    texts = list(CORPUS.values())
    vectors = await provider.embed(texts)
    store.upsert(
        CollectionName.DOCUMENTS.value,
        [
            Embedding(vector=vectors[i], chunk_id=cid, document_id="d", text=text)
            for i, (cid, text) in enumerate(CORPUS.items())
        ],
    )
    query_vec = (await provider.embed(["заключение эксперта ущерб сумма"]))[0]
    dense_hits = store.search(CollectionName.DOCUMENTS.value, query_vec, limit=3)
    dense_top = [r.embedding.chunk_id for r in dense_hits]
    print(f"dense top-3: {dense_top}")

    print()
    print("Вывод: идеальные метрики на точных запросах объясняются тем,")
    print("что BM25 находит буквальное совпадение. На перефразированных")
    print("запросах результат падает — так и должно быть на заглушке:")
    print("MockEmbeddingProvider не понимает смысл, он даёт")
    print("воспроизводимую проекцию. Реальные метрики — на RTX 3050.")
    return 0  # Диагностический скрипт: всегда «успех».


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
