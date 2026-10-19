"""Индекс резолютивных частей судебных решений корпуса.

Строит поиск по прошлым решениям: у проекта должен быть рядом ряд
похожих дел с тем, как суд постановил раньше. Индекс живёт отдельно от
пайплайна дела — это справочник, а не документы конкретного дела.

Отбор здесь мягче, чем в build_lora_dataset. Для обучения нужны были
решения с объяснимыми суммами; для поиска аналогов суммы не важны,
важно, что резолюция вообще есть и она разбирается. Поэтому в индекс
попадает всё, что удалось разобрать, — около восьми тысяч решений
против шестисот пар для обучения.

Заголовки вида «Р Е Ш И Л:» и блок завершения с подписью судьи
отбрасываются теми же функциями, что и при сборке обучения: иначе в
индекс попадёт то, что модель потом сочтёт за образец формулировки.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import re
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
INDEX_DIR = ROOT / "data" / "corpus_index"
COLLECTION = "corpus_operative"

sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT / "scripts"))

from app.config import EmbeddingProviderName, Settings  # noqa: E402
from app.embeddings import build_embedding_provider  # noqa: E402
from app.ingestion.chunking import chunk_text  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "build_lora_dataset", ROOT / "scripts" / "build_lora_dataset.py"
)
lora = importlib.util.module_from_spec(spec)
sys.modules["build_lora_dataset"] = lora
spec.loader.exec_module(lora)

spec2 = importlib.util.spec_from_file_location(
    "build_real_demo", ROOT / "scripts" / "build_real_demo.py"
)
base = importlib.util.module_from_spec(spec2)
sys.modules["build_real_demo"] = base
spec2.loader.exec_module(base)

#: Резолюция короче этого — это отписка («И СЧИТАЮ ВОЗМЕННЫМ»),
#: в поиске по аналогам она бесполезна.
MIN_OPERATIVE_CHARS = 300

#: Исходы дел в формулировках, которые реально встречаются в корпусе.
#: Порядок важен: «отказ от иска» это прекращение производства, а не
#: отказ в иске, и проверяться оно должно раньше «отказать». Без
#: «признать обоснованными» четверть дел, где суд не пишет слова
#: «удовлетворить», уходила в «не определён».
OUTCOMES: tuple[tuple[str, str], ...] = (
    ("оставить без рассмотрения", "оставлено без рассмотрения"),
    ("отказ от иска", "производство прекращено"),
    ("прекратить", "производство прекращено"),
    ("отказать", "отказ"),
    ("отклонить", "отказ"),
    ("частично", "удовлетворено частично"),
    ("удовлетворить", "удовлетворено"),
    ("признать обоснованными", "удовлетворено"),
)
SUBJECT = re.compile(
    r"о\s+(?:взыскании|возмещении|признании|расторжении|взыскани)[^.]{0,140}",
    re.I,
)


def outcome_of(operative: str) -> str:
    """Исход дела по формулировке резолюции."""
    lowered = operative.lower()
    for marker, name in OUTCOMES:
        if marker in lowered:
            return name
    return "не определён"


def subject_of(*sources: str) -> str:
    """Предмет спора одной строкой.

    Ищется по всей резолюции, а не только по шапке: в шапке предмета
    обычно нет, там «Решение по гражданскому делу», а формулировка
    «о взыскании задолженности...» стоит в самой резолюции.
    """
    for source in sources:
        match = SUBJECT.search(source)
        if match:
            return " ".join(match.group(0).split())[:200]
    return ""


def court_of(header: str) -> str:
    """Суд из шапки решения."""
    for line in header.splitlines():
        cleaned = " ".join(line.split())
        if "суд" in cleaned.lower() and len(cleaned) < 200:
            return cleaned
    return ""


PLACEHOLDER = re.compile(r"<[^>]{2,30}>")


def dedupe_key(operative: str) -> str:
    """Ключ для отсева одинаковых решений.

    Хэш берётся не от текста, а от текста без чисел и без
    плейсхолдеров обезличивания. Иначе в поиске рядом оказываются
    три почти одинаковых решения, отличающихся только суммой и
    реквизитами, — а это одно и то же дело по форме: банки и страховые
    пишут резолюции по одному шаблону.
    """
    normalized = PLACEHOLDER.sub("", operative)
    normalized = re.sub(r"\d+", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def operative_from(text: str) -> str | None:
    """Резолютивная часть, если она есть и её можно показать."""
    parts = base.split_decision(lora.normalize_headings(text))
    if not parts:
        return None
    operative = lora.operative_text(parts)
    if len(operative) < MIN_OPERATIVE_CHARS:
        return None
    return operative


def collect(paths: list[Path], limit: int) -> list[dict[str, Any]]:
    """Собрать решения с пригодной резолютивной частью."""
    import pandas as pd

    seen: set[str] = set()
    collected: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()

    for path in paths:
        if not path.exists():
            print(f"  пропускаю {path.name}: файла нет")
            continue
        frame = pd.read_parquet(path)
        if "text" not in frame.columns:
            print(f"  пропускаю {path.name}: нет колонки text")
            continue
        texts = [str(value) for value in frame["text"].tolist()]
        print(f"  {path.name}: {len(texts)} дел")

        for index, text in enumerate(texts):
            if limit and len(collected) >= limit:
                print(f"  достигнут предел {limit}")
                return collected
            operative = operative_from(text)
            if not operative:
                skipped["нет пригодной резолюции"] += 1
                continue
            digest = dedupe_key(operative)
            if digest in seen:
                skipped["дубликат"] += 1
                continue
            seen.add(digest)

            parts = base.split_decision(lora.normalize_headings(text))
            header = parts.get("header", "")
            cleaned = base.anonymize(operative)
            leaks = base.find_leaks(cleaned)
            if leaks:
                skipped["персональные данные"] += 1
                continue

            collected.append(
                {
                    "source": f"{path.stem}:{index}",
                    "operative": cleaned,
                    "outcome": outcome_of(cleaned),
                    "subject": subject_of(cleaned, header),
                    "court": court_of(header),
                }
            )

    print(f"  отбраковано: {dict(skipped.most_common())}")
    return collected


async def embed_with_retry(provider: Any, text: str, attempts: int = 6) -> list[float]:
    """Вектор с повторами при недоступности модели эмбеддингов.

    Прогон по всему корпусу идёт часами, и один разрыв соединения с
    Ollama посередине обрывал его целиком. Повтор с паузой дешевле
    потерянных часов: модель эмбеддингов может быть выгружена из
    памяти или пережить перезапуск.
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            vectors = await provider.embed([text])
            if vectors:
                return vectors[0]
            last = RuntimeError("модель вернула пустой вектор")
        except Exception as exc:  # noqa: BLE001
            last = exc
        wait = 5 * attempt
        print(f"    эмбеддинги недоступны ({attempt}/{attempts}), жду {wait} с")
        await asyncio.sleep(wait)
    raise RuntimeError(f"эмбеддинги не восстановились за {attempts} попыток") from last


def load_progress(index_path: Path) -> set[str]:
    """Источники решений, уже записанные в индекс."""
    path = index_path / "progress.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return set()
    return {str(item) for item in data.get("done", [])}


def save_progress(index_path: Path, done: set[str]) -> None:
    """Сохранить ход работ, чтобы перезапуск продолжил с места."""
    (index_path / "progress.json").write_text(
        json.dumps({"done": sorted(done)}, ensure_ascii=False), encoding="utf-8"
    )


async def embed_and_store(
    decisions: list[dict[str, Any]], index_path: Path, batch_size: int
) -> tuple[int, int]:
    """Построить векторы и записать их в локальный Qdrant."""
    from qdrant_client import QdrantClient, models

    cfg = Settings(
        app_env="development",
        embedding_provider=EmbeddingProviderName.LOCAL,
        ollama_enabled=True,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_sec=1800,
        embedding_batch_size=batch_size,
        storage_dir=index_path,
        chunk_size=800,
        chunk_overlap=120,
    )
    provider = build_embedding_provider(cfg)
    # Проверка до начала работы. Без неё падение выглядит как ошибка
    # соединения в середине многочасового прогона: на этой машине Ollama
    # то есть, то нет, и три запуска подряд ушли на одно и то же.
    if not await provider.health():
        raise RuntimeError(
            "Модель эмбеддингов недоступна. Обычно это значит, что не "
            "запущена Ollama:\n"
            "  $env:OLLAMA_MODELS='D:\\ollama\\models\\models'\n"
            "  $env:OLLAMA_HOST='127.0.0.1:11434'\n"
            "  D:\\ollama\\app\\ollama.exe serve"
        )
    print(f"эмбеддинги: {provider.name}, размерность {provider.dimension}")

    client = QdrantClient(path=str(index_path / "qdrant"))
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=models.VectorParams(
                size=provider.dimension, distance=models.Distance.COSINE
            ),
        )

    done = load_progress(index_path)
    if done:
        print(f"продолжаю: ранее записано решений {len(done)}")

    points: list[models.PointStruct] = []
    chunks_total = 0
    for number, decision in enumerate(decisions, start=1):
        if decision["source"] in done:
            continue
        for chunk in chunk_text(
            decision["operative"], document_id=decision["source"], settings=cfg
        ):
            vector = await embed_with_retry(provider, chunk.text)
            # Qdrant требует UUID. Идентификатор детерминированный:
            # пересборка индекса перезаписывает те же точки, а не
            # добавляет дубликаты.
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id))
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "source": decision["source"],
                        "text": chunk.text,
                        "outcome": decision["outcome"],
                        "subject": decision["subject"],
                        "court": decision["court"],
                    },
                )
            )
            chunks_total += 1

        if number % 25 == 0:
            client.upsert(collection_name=COLLECTION, points=points)
            print(f"  {number}/{len(decisions)} решений, кусков {chunks_total}")
            points = []

    if points:
        client.upsert(collection_name=COLLECTION, points=points)

    client.close()
    return len(decisions), chunks_total


async def search(index_path: Path, query: str, limit: int) -> int:
    """Показать похожие резолютивные части."""
    from qdrant_client import QdrantClient

    cfg = Settings(
        app_env="development",
        embedding_provider=EmbeddingProviderName.LOCAL,
        ollama_enabled=True,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_sec=1800,
        storage_dir=index_path,
    )
    provider = build_embedding_provider(cfg)
    client = QdrantClient(path=str(index_path / "qdrant"))
    vector = (await provider.embed([query]))[0]
    response = client.query_points(
        collection_name=COLLECTION,
        query=list(vector),
        limit=limit,
        with_payload=True,
    )
    hits = response.points

    print(f"запрос: {query}")
    print(f"найдено: {len(hits)}\n")
    for position, hit in enumerate(hits, start=1):
        payload = hit.payload or {}
        print(f"[{position}] сходство {hit.score:.3f} | исход {payload.get('source', '?')}")
        print(f"    исход дела: {payload.get('outcome', '?')}")
        print(f"    предмет: {payload.get('subject', '')[:120]}")
        print(f"    текст: {' '.join(str(payload.get('text', '')).split())[:260]}\n")

    client.close()
    return len(hits)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", nargs="*", default=[r"D:\ollama\hf_train.parquet"])
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--index", default=str(INDEX_DIR))
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--search", default="")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args(argv)

    index_path = Path(args.index)
    if args.search:
        # Число найденного не должно попадать в код возврата: ноль
        # найденного — это результат поиска, а не ошибка запуска.
        asyncio.run(search(index_path, args.search, args.top))
        return 0

    index_path.mkdir(parents=True, exist_ok=True)
    print("Читаю корпус")
    decisions = collect([Path(item) for item in args.corpus], args.limit)
    if not decisions:
        print("Ни одного пригодного решения — проверьте путь к корпусу.")
        return 1
    print(f"пригодных решений: {len(decisions)}")

    decisions_count, chunks = asyncio.run(
        embed_and_store(decisions, index_path, args.batch)
    )
    outcomes = Counter(item["outcome"] for item in decisions)
    (index_path / "manifest.json").write_text(
        json.dumps(
            {
                "решений": decisions_count,
                "кусков": chunks,
                "исходы": dict(outcomes.most_common()),
                "источники": [item["source"] for item in decisions],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(f"решений: {decisions_count}")
    print(f"кусков в индексе: {chunks}")
    print("исходы дел:")
    for name, count in outcomes.most_common():
        print(f"  {name}: {count}")
    print(f"индекс: {index_path}")
    print(f"поиск: python {Path(__file__).name} --search \"текст\"")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
