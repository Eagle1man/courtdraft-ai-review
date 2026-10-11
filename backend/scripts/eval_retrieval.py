"""Измерение метрик качества поиска (п.63).

Скрипт, а не тест: результат нужен как числа для отчёта, а тест
проверяет лишь пороги.

Провайдер эмбеддингов берётся из настроек (.env), а не задаётся
заглушкой: замер на заглушке показывает поведение заглушки, а не
системы. Фактическое имя провайдера печатается обязательно — при
недоступной модели провайдер молча уходит в резервный режим, и без
этой строки такой прогон выглядел бы как настоящий замер.

Запуск:
    .venv\\Scripts\\python.exe scripts\\eval_retrieval.py
    .venv\\Scripts\\python.exe scripts\\eval_retrieval.py --mock
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.embeddings import build_embedding_provider  # noqa: E402
from app.embeddings.base import Embedding  # noqa: E402
from app.embeddings.mock import MockEmbeddingProvider  # noqa: E402
from app.rag.retrieval import Document, Retriever  # noqa: E402
from app.rag.store import CollectionName, SearchFilters, VectorStore  # noqa: E402

DIM = 1024

# Синтетический корпус: релевантные chunk_id -> текст.
# Проверяем не «что-то нашлось», а нашёл ли поиск нужный фрагмент.
#
# Ключи обязаны быть в формате <case_id>:<index>: магазин берёт case_id
# именно из chunk_id. Без двоеточия фильтр отсекал бы все векторы, и
# плотный поиск молчал бы — метрики выглядели бы правдоподобно, а на
# деле измеряли бы только BM25.
CASE_ID = "case-1"

CORPUS: dict[str, str] = {
    "case-1:0": "Договор поставки заключён 15 мая 2019 года между истцом и ответчиком",
    "case-1:1": "Оплата по договору произведена в полном объёме, что подтверждается чеком",
    "case-1:2": "Ответчик в судебное заседание не явился, уважительных причин не сообщил",
    "case-1:3": "Размер ущерба определён заключением эксперта в сумме 150000 рублей",
    "case-1:4": "Истец требовал взыскания неустойки за просрочку исполнения обязательства",
    "case-1:5": "Ответчик представил возражения против суммы, заявив о ненадлежащем исполнении",
    "case-1:6": "Суд исследовал материалы дела и заслушал объяснения сторон",
    "case-1:7": "Протокол судебного заседания составлен секретарём и подписан участниками",
}

QUERIES: list[tuple[str, set[str]]] = [
    ("когда был заключён договор поставки", {"case-1:0"}),
    ("произведена ли оплата по договору", {"case-1:1"}),
    ("являлся ли ответчик в судебное заседание", {"case-1:2"}),
    ("какова сумма ущерба по заключению эксперта", {"case-1:3"}),
    ("какие требования заявил истец", {"case-1:4"}),
    ("какие возражения представил ответчик", {"case-1:5"}),
    ("что делал суд на заседании", {"case-1:6"}),
    ("кем составлен протокол заседания", {"case-1:7"}),
]


async def build_retriever(use_mock: bool = False) -> Retriever:
    """Собрать поиск над корпусом.

    Возвращает ретрайвер и описание того, какая модель реально
    использовалась: «local» может оказаться резервной заглушкой,
    и об этом должен быть известен читатель отчёта.
    """
    from qdrant_client import QdrantClient

    if use_mock:
        provider = MockEmbeddingProvider(dimension=DIM)
        label = "заглушка (--mock)"
    else:
        provider = build_embedding_provider()
        label = f"{provider.name}: {getattr(provider, '_model', '?')}"

        if not await provider.health():
            # Молча уйти в резерв нельзя: замер станет бессмысленным,
            # а выглядеть будет как настоящий результат.
            label += " — НЕДОСТУПНА, используется резерв"

    print(f"Провайдер эмбеддингов: {label}")
    print(f"Размерность векторов:  {provider.dimension}")
    print()

    store = VectorStore(QdrantClient(":memory:"), dimension=provider.dimension)
    retriever = Retriever(store, provider)

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
        [Document(chunk_id=e.chunk_id, text=e.text, case_id=CASE_ID) for e in embs]
    )
    return retriever


async def main() -> int:
    parser = argparse.ArgumentParser(description="Метрики качества поиска")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="измерять на заглушке (для сравнения с настоящей моделью)",
    )
    args = parser.parse_args()

    retriever = await build_retriever(use_mock=args.mock)

    recall_at_5: list[float] = []
    recall_at_10: list[float] = []
    reciprocal_ranks: list[float] = []

    print(f"{'запрос':<48} {'R@5':>5} {'R@10':>6} {'MRR':>6}")
    print("-" * 70)

    for query, relevant in QUERIES:
        result5 = await retriever.search(query, limit=5, filters=SearchFilters(case_id=CASE_ID))
        result10 = await retriever.search(query, limit=10, filters=SearchFilters(case_id=CASE_ID))

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
    # находит буквальное совпадение. Поэтому честная проверка смысла
    # живёт в отдельном скрипте eval_sanity.py, где слов из корпуса
    # в запросе нет вовсе.
    #
    # Что эти метрики действительно проверяют:
    #   - чанкинг и индексация не теряют и не дублируют фрагменты;
    #   - payload-фильтры изолируют дела;
    #   - RRF объединяет два списка корректно;
    #   - provenance переживает запись и поиск.
    #
    # Метрики на совпадающих словах проверяют индексацию, а не смысл.
    # Смысл измеряется на перефразированных запросах в eval_sanity.py.
    ok = mean(recall_at_10) >= 0.90 and mrr >= 0.40
    print()
    print("ИТОГ:", "PASS" if ok else "FAIL (порог Recall@10 >= 0.90, MRR >= 0.40)")
    print("ВНИМАНИЕ: эти метрики проверяют индексацию, не смысл.")
    print("          Смысл: scripts/eval_sanity.py")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
