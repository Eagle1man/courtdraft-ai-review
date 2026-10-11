"""Демонстрационный прогон CourtDraft AI (ТЗ п.41, п.60).

Проходит весь путь на реальных материалах дела DEMO-001:

    дело -> документы -> разбор -> чанки -> эмбеддинги -> индекс
         -> пакет доказательств -> проект решения -> проверка -> версия

Работает БЕЗ GPU и БЕЗ облака. Модель — локальная Ollama.

Запуск:
    .venv\\Scripts\\python.exe scripts\\demo.py
    .venv\\Scripts\\python.exe scripts\\demo.py --provider mock   # мгновенно
    .venv\\Scripts\\python.exe scripts\\demo.py --only-section motivating
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.agents.draft_agent import generate_draft  # noqa: E402
from app.agents.evidence_pack import (  # noqa: E402
    EvidencePack,
    build_evidence_pack,
    load_template,
)
from app.config import EmbeddingProviderName, LLMProviderName, Settings  # noqa: E402
from app.db.repositories import AuditRepository, DocumentRepository  # noqa: E402
from app.db.session import create_engine_and_session  # noqa: E402
from app.embeddings import build_embedding_provider  # noqa: E402
from app.ingestion.chunking import chunk_text  # noqa: E402
from app.ingestion.extract import detect_mime_type, extract_text, guess_document_type  # noqa: E402
from app.llm import build_llm_provider  # noqa: E402
from app.rag.store import CollectionName, VectorStore  # noqa: E402
from app.services.case_service import CaseService, session_scope  # noqa: E402
from app.verification.engine import verify_draft  # noqa: E402

DEMO_DIR = BACKEND.parent / "data" / "demo"
OUTPUT_DIR = BACKEND.parent / "data" / "demo" / "output"
# Журнал прогона — рядом с выводом, но ВНЕ очищаемого каталога:
# reset_output() удаляет содержимое OUTPUT_DIR, и журнал внутри него
# пришлось бы удалять вместе с открытым файлом.
LOG_PATH = BACKEND.parent / "data" / "demo" / "demo_real.log"


def say(message: str = "", log: object = None) -> None:
    """Печать в консоль и, если задан, в файл в UTF-8.

    Консоль Windows не печатает кириллицу, поэтому отчёт дублируется
    в файл — без него результат невозможно ни прочитать, ни показать.
    """
    print(message)
    if log is not None:
        log.write(message + "\n")  # type: ignore[attr-defined]
        log.flush()  # type: ignore[attr-defined]


def banner(step: str, title: str, log: object = None) -> None:
    say("", log)
    say("=" * 78, log)
    say(f"  {step}. {title}", log)
    say("=" * 78, log)


def reset_output() -> None:
    """Очистить результаты прошлого прогона.

    Демо — это демонстрация, а не накопитель данных. Повторный запуск
    обязан давать тот же результат, иначе его невозможно проверить.

    Журнал прогона лежит рядом с каталогом вывода и не удаляется: иначе
    демо стёрло бы файл, в который само пишет.
    """
    if OUTPUT_DIR.exists():
        for item in OUTPUT_DIR.iterdir():
            if not item.is_file():
                continue
            try:
                item.unlink(missing_ok=True)
            except PermissionError:
                # Занятый файл (журнал, открытый просмотрщиком) не должен
                # ронять демо из-за уборки.
                say(f"  (не удалось удалить {item.name}: файл занят)")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def make_settings(provider: str, workdir: Path) -> Settings:
    """Настройки прогона. БД и индекс — во временном каталоге.

    Эмбеддинги берутся из настроек, а не задаются заглушкой: на прогоне
    с настоящей моделью должен быть настоящий и поиск, иначе замеры
    показывают поведение заглушки, а не системы.
    """
    llm = LLMProviderName.MOCK if provider == "mock" else LLMProviderName.OLLAMA
    # При заглушке LLM эмбеддинги тоже оставляем заглушкой: иначе
    # прогон «мгновенный» стал бы ждать настоящую модель.
    embeddings = (
        EmbeddingProviderName.MOCK
        if provider == "mock"
        else EmbeddingProviderName.LOCAL
    )
    return Settings(
        app_env="development",
        llm_provider=llm,
        embedding_provider=embeddings,
        ollama_enabled=provider != "mock",
        ollama_model="qwen2.5:1.5b",
        ollama_base_url="http://127.0.0.1:11434",
        ollama_timeout_sec=1800,
        ollama_num_ctx=2048,
        # Русские тексты длиннее английских в токенах: батч поменьше,
        # иначе часть фрагментов обрезается по контексту модели.
        embedding_batch_size=8,
        database_url=f"sqlite+aiosqlite:///{(workdir / 'demo.db').as_posix()}",
        storage_dir=workdir,
        documents_dir=workdir / "documents",
        demo_dir=DEMO_DIR,
        laws_dir=BACKEND.parent / "data" / "laws",
        templates_dir=BACKEND.parent / "data" / "templates",
        chunk_size=800,
        chunk_overlap=120,
    )


async def run_demo(
    provider: str,
    only_sections: list[str] | None,
    log: object = None,
) -> int:
    started = time.perf_counter()

    # Демо обязано быть воспроизводимым: каждый запуск начинается с нуля.
    # Иначе второй прогон падает на «дело уже существует», и проверить
    # конвейер повторно невозможно.
    reset_output()

    settings = make_settings(provider, OUTPUT_DIR)
    settings.ensure_dirs()

    # ── Шаг 0. Режим ────────────────────────────────────────────────
    banner("0", "РЕЖИМ РАБОТЫ", log)
    llm = build_llm_provider(settings)
    if provider == "mock":
        say("  LLM:      MockLLMProvider (мгновенно, реальная модель не вызывается)", log)
    else:
        say(f"  LLM:      Ollama, модель {settings.ollama_model}", log)
        say(f"           адрес {settings.ollama_base_url}", log)
        alive = await llm.health()
        say(f"  доступна: {'да' if alive else 'НЕТ — будет запись об ошибке'}", log)

    say(
            "  Embeddings: "
            + (
                "заглушка (режим mock)"
                if provider == "mock"
                else f"{settings.embedding_model}, {settings.embedding_dim} измерений"
            ),
            log,
        )
    say("  База:       SQLite (временная)", log)
    say("  Индекс:     встроенный Qdrant (в памяти)", log)
    say("  GPU:        не требуется", log)

    # ── Шаг 1. Материалы дела ──────────────────────────────────────
    banner("1", "МАТЕРИАЛЫ ДЕЛА (синтетические)", log)
    demo_files = sorted(DEMO_DIR.glob("*.txt"))
    if not demo_files:
        say("  ОШИБКА: нет демо-документов. Запустите scripts/make_demo_case.py", log)
        return 1

    manifest_path = DEMO_DIR / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    say(f"  {manifest.get('warning', 'SYNTHETIC DEMO DATA')}", log)
    say("", log)
    documents: list[tuple[str, str, str]] = []
    for path in demo_files:
        data = path.read_bytes()
        extracted = extract_text(path.name, data, settings=settings)
        doc_type = guess_document_type(path.name, extracted.text)
        documents.append((path.name, extracted.text, doc_type))
        say(f"  {path.name:<26} {doc_type:<15} {len(extracted.text):>6} симв.", log)

    # ── Шаг 2. Дело и разбор документов ─────────────────────────────
    banner("2", "СОЗДАНИЕ ДЕЛА И РАЗБОР ДОКУМЕНТОВ", log)

    engine_ctx = create_engine_and_session(settings)
    engine, factory = await engine_ctx.__aenter__()
    await ensure_schema_for(engine)

    total_chunks = 0
    pack: EvidencePack

    async with session_scope(factory) as session:
        service = CaseService(session)
        case = await service.create_case(
            manifest.get("case_number", "DEMO-001"),
            manifest.get("court", "Демонстрационный районный суд"),
            "civil",
            category=manifest.get("category", "договорные споры"),
            is_synthetic=True,
            actor="demo",
        )
        say(f"  дело № {case.case_number} создано (id={str(case.id)[:8]}…)", log)

        repo = DocumentRepository(session)
        for filename, text, doc_type in documents:
            import hashlib

            document = await repo.add(
                __import__("app.models.entities", fromlist=["CaseDocument"]).CaseDocument(
                    case_id=case.id,
                    filename=filename,
                    document_type=doc_type,
                    mime_type=detect_mime_type(filename),
                    page_count=1,
                    text=text,
                    metadata_json={"demo": True},
                    sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                )
            )
            chunks = chunk_text(text, document_id=str(document.id), settings=settings)
            total_chunks += len(chunks)
            say(f"  {filename:<26} фрагментов: {len(chunks)}", log)

        # ── Шаг 3. Эмбеддинги и индекс ────────────────────────────
        banner("3", "ЭМБЕДДИНГИ И ИНДЕКС", log)
        from qdrant_client import QdrantClient

        store = VectorStore(
            QdrantClient(":memory:"), dimension=settings.embedding_dim
        )
        # Провайдер берётся из настроек: на прогоне с настоящей моделью
        # поиск должен быть настоящим, иначе замер бессмысленен.
        embeddings = build_embedding_provider(settings)
        say(
            f"  провайдер: {embeddings.name}, размерность {embeddings.dimension}",
            log,
        )
        if not await embeddings.health():
            say(
                "  ВНИМАНИЕ: модель эмбеддингов недоступна. "
                "Индекс будет заполнен заглушкой — замеры покажут "
                "поведение заглушки, а не системы.",
                log,
            )
        from app.embeddings.base import Embedding

        rows = await repo.list_for_case(case.id)
        indexed = 0
        for document in rows:
            chunks = chunk_text(document.text, document_id=str(document.id), settings=settings)
            vectors = await embeddings.embed([c.text for c in chunks])
            store.upsert(
                CollectionName.DOCUMENTS.value,
                [
                    Embedding(
                        vector=vectors[i],
                        chunk_id=c.anchor,
                        document_id=str(document.id),
                        filename=document.filename,
                        document_type=document.document_type,
                        text=c.text[:4000],
                    )
                    for i, c in enumerate(chunks)
                ],
            )
            indexed += len(chunks)

        stats = store.stats(CollectionName.DOCUMENTS.value)
        say(f"  фрагментов: {total_chunks}, в индексе: {stats.points}", log)
        say(
            f"  коллекция: {CollectionName.DOCUMENTS.value}, "
            f"размерность {store.dimension}",
            log,
        )

        # ── Шаг 4. Поиск по делу ───────────────────────────────────
        banner("4", "ПОИСК ПО МАТЕРИАЛАМ ДЕЛА (проверка индекса)", log)
        from app.rag.retrieval import Document, Retriever

        retriever = Retriever(store, embeddings, settings)
        docs_for_bm25 = [
            Document(
                chunk_id=c.anchor,
                text=c.text,
                case_id=str(case.id),
                document_id=str(document.id),
                document_type=document.document_type,
                filename=document.filename,
            )
            for document in rows
            for c in chunk_text(document.text, document_id=str(document.id), settings=settings)
        ]
        retriever.index_for_bm25(docs_for_bm25)

        for query in ("договор поставки", "оплата задолженности", "заключение эксперта"):
            result = await retriever.search(query, limit=3)
            say(f"  «{query}» → найдено {len(result.results)} (метод: {result.method})", log)

        # ── Шаг 5. Пакет доказательств ─────────────────────────────
        banner("5", "ПАКЕТ ДОКАЗАТЕЛЬСТВ", log)
        pack = build_evidence_pack(
            case.case_number,
            case.court_name,
            case.category,
            rows,
            settings=settings,
        )
        say(pack.summary(), log)
        say("", log)
        say(f"  фактов с источником: {len(pack.items)}", log)
        for category in pack.categories_present():
            say(f"    {category:<22} {len(pack.by_category(category)):>3}", log)
        if pack.gaps:
            say("", log)
            say("  ПРОБЕЛЫ (модель получит эти указания, а не выдумает):", log)
            for gap in pack.gaps:
                say(f"   - {gap}", log)

        await AuditRepository(session).log(
            "demo.evidence_pack", case_id=case.id, actor="demo",
            facts=len(pack.items), gaps=len(pack.gaps),
        )

    # ── Шаг 6. Проект решения ────────────────────────────────────────
    banner("6", "ФОРМИРОВАНИЕ ПРОЕКТА РЕШЕНИЯ", log)
    template = load_template(settings)
    say(f"  шаблон: {template['name']} — {template['legal_basis']}", log)
    say(f"  разделов: {len(template['sections'])}", log)
    say("", log)

    if only_sections:
        say(f"  ограничение прогона: только разделы {only_sections}", log)
        say("", log)

    say("  Генерация (это самая долгая часть на CPU):", log)
    say("", log)
    draft = await generate_draft(
        pack, template, provider=llm, settings=settings, only_sections=only_sections
    )

    for section in draft.sections:
        flag = "MOCK" if section.is_mock else "REAL"
        review = " ⚠ требует проверки" if section.needs_review else ""
        say(
            f"    [{flag}] {section.name:<24} {section.latency_ms/1000:>6.1f} с"
            f" · {len(section.text):>5} симв.{review}",
            log,
        )

    # ── Шаг 7. Проверка ─────────────────────────────────────────────
    banner("7", "ПРОВЕРКА ПРОЕКТА", log)
    report = verify_draft(draft, pack)
    say(report.human_summary(), log)

    stats = draft.stats()
    say("", log)
    say(f"  разделов: {stats['sections']}, символов: {stats['characters']}", log)
    say(f"  ссылок на источники: {stats['citations']}", log)
    say(f"  утверждений без источника: {report.unsupported_claims}", log)
    say(f"  время генерации: {draft.total_latency_ms/1000:.1f} с", log)

    # ── Шаг 8. Сохранение ──────────────────────────────────────────
    banner("8", "СОХРАНЕНИЕ РЕЗУЛЬТАТА", log)

    draft_path = OUTPUT_DIR / "draft.md"
    draft_path.write_text(
        f"# ПРОЕКТ РЕШЕНИЯ\n\n"
        f"> {manifest.get('warning', 'SYNTHETIC DEMO DATA')}\n\n"
        f"Дело № {draft.case_number}\n\n---\n\n{draft.text}\n\n---\n\n"
        f"## Проверка\n\n{report.human_summary()}\n",
        encoding="utf-8",
    )
    say(f"  проект:     {draft_path}", log)
    say(f"  проверка:   {draft_path.name} (раздел «Проверка» в конце)", log)

    json_path = OUTPUT_DIR / "result.json"
    json_path.write_text(
        json.dumps(
            {
                "warning": manifest.get("warning", "SYNTHETIC DEMO DATA"),
                "mode": provider,
                "model": settings.ollama_model if provider != "mock" else "mock",
                "case_number": pack.case_number,
                "evidence_pack": pack.to_dict(),
                "draft": {
                    "text": draft.text,
                    "sections": [
                        {
                            "key": s.key,
                            "name": s.name,
                            "text": s.text,
                            "is_mock": s.is_mock,
                            "needs_review": s.needs_review,
                            "citations": s.citations,
                        }
                        for s in draft.sections
                    ],
                    "sources": draft.sources(),
                },
                "verification": report.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    say(f"  json:       {json_path}", log)

    await engine_ctx.__aexit__(None, None, None)

    # ── Итог ────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - started
    banner("ИТОГ", "ДЕМО ПРОЙДЕНО", log)
    mode_label = "MOCK (заглушка)" if provider == "mock" else f"REAL, {settings.ollama_model}"
    say(f"  общее время: {elapsed:.1f} с", log)
    say(f"  режим:       {mode_label}", log)
    say(f"  статус проверки: {report.status.value}", log)
    say("", log)
    say("  Проект сгенерирован и проверен. Итоговый текст:", log)
    say(f"    {draft_path}", log)
    say("", log)
    say("  ВАЖНО: это ПРОЕКТ, а не решение суда.", log)
    say("  Проверка и утверждение — за человеком.", log)
    return 0


async def ensure_schema_for(engine) -> None:  # noqa: ANN001
    """Создать схему БД для демо."""
    from app.db.session import create_all

    await create_all(engine)


def main() -> int:
    parser = argparse.ArgumentParser(description="Демонстрация CourtDraft AI")
    parser.add_argument(
        "--provider", choices=["ollama", "mock"], default="ollama",
        help="ollama — реальная модель; mock — мгновенная заглушка",
    )
    parser.add_argument(
        "--only-section", action="append", dest="sections",
        help="сгенерировать только указанный раздел (можно повторять)",
    )
    parser.add_argument(
        "--log", default="", help="дублировать вывод в файл (UTF-8)"
    )
    args = parser.parse_args()

    # Консоль Windows по умолчанию не печатает кириллицу, поэтому весь
    # отчёт пишется ещё и в файл в UTF-8 — иначе результат невозможно
    # ни прочитать, ни показать.
    log_file = None
    if args.log:
        # noqa SIM115: файл держится открытым весь асинхронный прогон и
        # закрывается в finally. Контекстный менеджер здесь не подходит —
        # прогон живёт дольше, чем блок чтения.
        log_file = open(args.log, "w", encoding="utf-8")  # noqa: SIM115

    try:
        return asyncio.run(run_demo(args.provider, args.sections, log_file))
    except KeyboardInterrupt:
        say("\nПрервано пользователем.", log_file)
        return 130
    finally:
        if log_file is not None:
            log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
