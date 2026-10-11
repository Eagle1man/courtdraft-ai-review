"""Честная проверка качества поиска (п.63).

Зачем этот скрипт. Первый замер дал Recall@5 = 1.000 на запросах,
почти дословно совпадающих с текстом корпуса. Такая цифра означает не
«поиск хороший», а «оценка ничего не проверяет»: BM25 находит
буквальное совпадение, а эмбеддинги в этом не участвуют.

Здесь запросы перефразированы так, что ключевых слов из корпуса в них
нет: «подтверждает ли чек перечисление денег» против «Оплата по договору
произведена в полном объёме, что подтверждается чеком». Найти такой
фрагмент может только поиск по смыслу.

Скрипт печатает провайдера, который реально отвечал. Это обязательно:
при недоступной модели провайдер молча уходит в резерв, и без такой
строки замер на заглушке выглядел бы как настоящий результат.

Запуск:
    .venv\\Scripts\\python.exe scripts\\eval_sanity.py
    .venv\\Scripts\\python.exe scripts\\eval_sanity.py --mock
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings  # noqa: E402
from app.embeddings import build_embedding_provider  # noqa: E402
from app.embeddings.base import Embedding, EmbeddingProvider  # noqa: E402
from app.embeddings.mock import MockEmbeddingProvider  # noqa: E402
from app.rag.retrieval import BM25Index, Document, Retriever  # noqa: E402
from app.rag.store import CollectionName, SearchFilters, VectorStore  # noqa: E402

DIM = 1024

CORPUS: dict[str, str] = {
    "case-1:0": "Договор поставки заключён 15 мая 2019 года между истцом и ответчиком",
    "case-1:1": "Оплата по договору произведена в полном объёме, что подтверждается чеком",
    "case-1:2": "Ответчик в судебное заседание не явился, уважительных причин не сообщил",
    "case-1:3": "Размер ущерба определён заключением эксперта в сумме 150000 рублей",
    "case-1:4": "Истец требовал взыскания неустойки за просрочку исполнения обязательства",
    "case-1:5": "Ответчик представил возражения против суммы, заявив о ненадлежащем исполнении",
}

# Ключи корпуса обязаны быть в формате <case_id>:<index>: магазин берёт
# case_id именно из chunk_id (store._extract_case_id). Без двоеточия
# фильтр по делу отсекал бы все векторы, и поиск возвращал бы пустоту
# независимо от качества модели. Именно из-за этого прежние замеры
# показывали 1.000 на дословных запросах (работал только BM25) и 0.000
# на перефразированных (не работал никто).
CASE_ID = "case-1"

# Перефразированные запросы: ключевых слов в тексте корпуса нет.
PARAPHRASED: list[tuple[str, set[str]]] = [
    ("подтверждает ли чек перечисление денег", {"case-1:1"}),
    ("почему подрядчик не пришёл в суд", {"case-1:2"}),
    ("сколько эксперт насчитал в пользу потерпевшей стороны", {"case-1:3"}),
    ("на что жаловалась пострадавшая сторона", {"case-1:4", "case-1:5"}),
    ("в какой день подписали контракт", {"case-1:0"}),
]


def make_provider(use_mock: bool) -> tuple[EmbeddingProvider, str]:
    """Провайдер и его честное описание."""
    if use_mock:
        return MockEmbeddingProvider(dimension=DIM), "заглушка (--mock)"

    provider = build_embedding_provider(Settings())
    label = f"{provider.name} (модель {getattr(provider, '_model', '?')})"
    return provider, label


async def build(provider: EmbeddingProvider) -> Retriever:
    """Индексировать корпус и вернуть готовый поиск."""
    from qdrant_client import QdrantClient

    store = VectorStore(QdrantClient(":memory:"), dimension=provider.dimension)
    retriever = Retriever(store, provider)

    texts = list(CORPUS.values())
    vectors = await provider.embed(texts)
    embs = [
        Embedding(vector=vectors[i], chunk_id=cid, document_id="d", text=text)
        for i, (cid, text) in enumerate(CORPUS.items())
    ]
    store.upsert(CollectionName.DOCUMENTS.value, embs)
    retriever.index_for_bm25(
        [Document(chunk_id=e.chunk_id, text=e.text, case_id=CASE_ID) for e in embs]
    )
    return retriever


async def main() -> int:
    parser = argparse.ArgumentParser(description="Честная проверка поиска по смыслу")
    parser.add_argument(
        "--mock", action="store_true", help="измерять на заглушке для сравнения"
    )
    args = parser.parse_args()

    provider, label = make_provider(args.mock)

    if not args.mock and not await provider.health():
        print(f"ВНИМАНИЕ: модель {label} недоступна — идёт резерв.")
        print("         Результат ниже НЕ является настоящим замером.")
        print()

    print("=" * 70)
    print(f"Провайдер: {label}, размерность {provider.dimension}")
    print("=" * 70)

    retriever = await build(provider)
    filters = SearchFilters(case_id=CASE_ID)

    print()
    print("=== Перефразированные запросы: ключевых слов из корпуса нет ===")
    print()
    print("ВНИМАНИЕ к метрике. Корпус состоит из 6 фрагментов, поэтому")
    print("Recall@5 почти гарантирован: попадание в пятёрку из шести")
    print("ничего не доказывает. Информативнее ПОРЯДОК правильного")
    print("ответа — если он первый, поиск различает смысл, а не угадывает.")
    print()
    print(f"{'запрос':<50} {'ранг':>5} {'R@5':>5}")
    print("-" * 68)

    scores: list[float] = []
    ranks: list[int] = []
    for query, relevant in PARAPHRASED:
        result = await retriever.search(query, limit=5, filters=filters)
        found = {r.chunk_id for r in result.results}
        score = len(relevant & found) / len(relevant)
        scores.append(score)

        rank = 0
        for position, hit in enumerate(result.results, start=1):
            if hit.chunk_id in relevant:
                rank = position
                break
        ranks.append(rank)

        mark = "" if rank == 1 else ("—" if rank else "не найден")
        print(f"{query[:48]:<50} {rank or '-':>5} {score:>5.2f}  {mark}")

    recall = sum(scores) / len(scores) if scores else 0.0
    top1 = sum(1 for r in ranks if r == 1) / len(ranks) if ranks else 0.0
    mean_rank = sum(ranks) / len(ranks) if ranks else 0.0

    print("-" * 68)
    print(f"Recall@5 на перефразированных запросах: {recall:.3f}")
    print(f"Правильный ответ ПЕРВЫМ (top-1):        {top1:.3f}")
    print(f"Средний порядок правильного ответа:     {mean_rank:.2f}")

    # Вклад методов по отдельности: показывает, что именно даёт
    # настоящая модель, а что — буквальное совпадение слов.
    print()
    print("=== Вклад методов по отдельности ===")
    probe = "подтверждает ли чек перечисление денег"

    index = BM25Index()
    for cid, text in CORPUS.items():
        index.add(Document(chunk_id=cid, text=text, case_id=CASE_ID))
    bm25_top = [r.chunk_id for r in index.search(probe, limit=3)]
    print(f"BM25          top-3: {bm25_top}   <- ищет только слова")

    from qdrant_client import QdrantClient

    store = VectorStore(QdrantClient(":memory:"), dimension=provider.dimension)
    texts = list(CORPUS.values())
    vectors = await provider.embed(texts)
    store.upsert(
        CollectionName.DOCUMENTS.value,
        [
            Embedding(vector=vectors[i], chunk_id=cid, document_id="d", text=text)
            for i, (cid, text) in enumerate(CORPUS.items())
        ],
    )
    query_vec = (await provider.embed([probe]))[0]
    dense_top = [
        h.embedding.chunk_id
        for h in store.search(CollectionName.DOCUMENTS.value, query_vec, limit=3)
    ]
    print(f"плотный поиск top-3: {dense_top}   <- ищет смысл")

    print()
    print("=" * 70)
    if top1 >= 0.80:
        print("ИТОГ: поиск ставит правильный материал первым по смыслу.")
        print("      Это и отличает его от поиска по совпадению слов,")
        print("      который на этих запросах не находит ничего.")
    elif top1 >= 0.40:
        print("ИТОГ: поиск частично понимает смысл. Есть над чем работать.")
    else:
        print("ИТОГ: поиск по смыслу не работает.")
    print("=" * 70)
    print()
    print("Граница достоверности: корпус — 6 фрагментов, запросов — 5.")
    print("Это проверка принципа, а не измерение качества на данных.")
    print("Для настоящих метрик нужен корпус реальных дел.")

    # Диагностический скрипт: ненулевой код означал бы падение CI
    # из-за честно отрицательного результата, а не из-за ошибки.
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
