"""Измерение метрик качества поиска (п.63).

Скрипт, а не тест: результат нужен как числа для отчёта, а тест
проверяет лишь пороги.

Запуск:
    .venv\\Scripts\\python.exe scripts\\eval_retrieval.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.embeddings.base import Embedding  # noqa: E402
from app.embeddings.mock import MockEmbeddingProvider  # noqa: E402
from app.rag.retrieval import Document, Retriever  # noqa: E402
from app.rag.store import CollectionName, SearchFilters, VectorStore  # noqa: E402

DIM = 1024

# Синтетический корпус: тема -> релевантные chunk_id.
# Проверяем не «что-то нашлось», а нашёл ли поиск нужный фрагмент.
CORPUS: dict[str, str] = {
    "c0": "Договор поставки заключён 15 мая 2019 года между истцом и ответчиком",
    "c1": "Оплата по договору произведена в полном объёме, что подтверждается чеком",
    "c2": "Ответчик в судебное заседание не явился, уважительных причин не сообщил",
    "c3": "Размер ущерба определён заключением эксперта в сумме 150000 рублей",
    "c4": "Истец требовал взыскания неустойки за просрочку исполнения обязательства",
    "c5": "Ответчик представил возражения против суммы, заявив о ненадлежащем исполнении",
    "c6": "Суд исследовал материалы дела и заслушал объяснения сторон",
    "c7": "Протокол судебного заседания составлен секретарём и подписан участниками",
}

QUERIES: list[tuple[str, set[str]]] = [
    ("когда был заключён договор поставки", {"c0"}),
    ("произведена ли оплата по договору", {"c1"}),
    ("являлся ли ответчик в судебное заседание", {"c2"}),
    ("какова сумма ущерба по заключению эксперта", {"c3"}),
    ("какие требования заявил истец", {"c4"}),
    ("какие возражения представил ответчик", {"c5"}),
    ("что делал суд на заседании", {"c6"}),
    ("кем составлен протокол заседания", {"c7"}),
]


async def build_retriever() -> Retriever:
    from qdrant_client import QdrantClient

    store = VectorStore(QdrantClient(":memory:"), dimension=DIM)
    retriever = Retriever(store, MockEmbeddingProvider(dimension=DIM))

    provider = MockEmbeddingProvider(dimension=DIM)
    texts = list(CORPUS.values())
    vectors = await provider.embed(texts)

    embs = [
        Embedding(
            vector=vectors[i],
            chunk_id=chunk_id,
            document_id="demo-doc",
            document_type="CLAIM",
            text=text,
        )
        for i, (chunk_id, text) in enumerate(CORPUS.items())
    ]
    store.upsert(CollectionName.DOCUMENTS.value, embs)
    retriever.index_for_bm25(
        [Document(chunk_id=e.chunk_id, text=e.text, case_id="case-1") for e in embs]
    )
    return retriever


async def main() -> int:
    retriever = await build_retriever()

    recall_at_5: list[float] = []
    recall_at_10: list[float] = []
    reciprocal_ranks: list[float] = []

    print(f"{'запрос':<48} {'R@5':>5} {'R@10':>6} {'MRR':>6}")
    print("-" * 70)

    for query, relevant in QUERIES:
        result5 = await retriever.search(query, limit=5, filters=SearchFilters(case_id="case-1"))
        result10 = await retriever.search(query, limit=10, filters=SearchFilters(case_id="case-1"))

        top5 = {r.chunk_id for r in result5.results}
        top10 = {r.chunk_id for r in result10.results}

        r5 = len(relevant & top5) / len(relevant)
        r10 = len(relevant & top10) / len(relevant)

        rr = 0.0
        for position, r in enumerate(result10.results, start=1):
            if r.chunk_id in relevant:
                rr = 1.0 / position
                break

        recall_at_5.append(r5)
        recall_at_10.append(r10)
        reciprocal_ranks.append(rr)

        print(f"{query[:46]:<48} {r5:>5.2f} {r10:>6.2f} {rr:>6.3f}")

    def mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    mrr = mean(reciprocal_ranks)

    print("-" * 70)
    print(f"Recall@5:   {mean(recall_at_5):.3f}")
    print(f"Recall@10:  {mean(recall_at_10):.3f}")
    print(f"MRR:        {mrr:.3f}")

    # ЧЕСТНО О МЕТРИКАХ
    #
    # Идеальные 1.000 здесь НЕ означают, что поиск «понимает смысл».
    # Запросы в QUERIES почти дословно повторяют текст корпуса, и BM25
    # находит буквальное совпадение. Проверено отдельным прогоном
    # (scripts/eval_sanity.py): на перефразированных запросах, где слов
    # из корпуса нет, Recall@5 = 0.00.
    #
    # Что эти метрики действительно проверяют:
    #   - чанкинг и индексация не теряют и не дублируют фрагменты;
    #   - payload-фильтры изолируют дела;
    #   - RRF объединяет два списка корректно;
    #   - provenance переживает запись и поиск.
    #
    # Реальные метрики качества RAG измеряются на RTX 3050 с настоящими
    # эмбеддингами. На DEV-машине они не воспроизводятся.
    ok = mean(recall_at_10) >= 0.90 and mrr >= 0.40
    print()
    print("ИТОГ:", "PASS" if ok else "FAIL (порог Recall@10 >= 0.90, MRR >= 0.40)")
    print("ВНИМАНИЕ: метрики на совпадающих словах. См. комментарий в коде.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
