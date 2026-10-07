"""Тесты слоя данных (Фаза 3).

БД — временная SQLite в памяти: тесты не должны требовать ни PostgreSQL,
ни Docker, ни сети (п.50). Тот же код работает на PostgreSQL — разница
только в DATABASE_URL.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db.repositories import (
    AnalysisRepository,
    AuditRepository,
    CaseRepository,
    DocumentRepository,
    DraftRepository,
)
from app.db.session import create_all, create_engine_and_session, drop_all, is_sqlite
from app.models.entities import (
    Case,
    CaseDocument,
    CaseStatus,
    DocumentChunk,
    DocumentType,
    DraftStatus,
    Severity,
    VerificationStatus,
)
from app.services.case_service import CaseService, session_scope


@pytest_asyncio.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """Движок на временной файловой SQLite.

    Файл, а не :memory:, потому что пул соединений SQLite в памяти
    создаёт отдельную базу на каждое соединение — асинхронный код
    открывает их несколько.
    """
    db_file = tmp_path / "test.db"

    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    manager = create_engine_and_session(_settings_for(url))
    eng, _factory = await manager.__aenter__()

    await create_all(eng)
    try:
        yield eng
    finally:
        await drop_all(eng)
        await manager.__aexit__(None, None, None)


def _settings_for(url: str):  # noqa: ANN202 - тестовый хелпер
    """Настройки с принудительным DATABASE_URL."""
    from app.config import Settings

    return Settings(database_url=url)


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture
async def case(session: AsyncSession) -> Case:
    repo = CaseRepository(session)
    created = await repo.create(
        case_number="TEST-001",
        court_name="Тестовый суд",
        case_type="civil",
    )
    await session.commit()
    return created


class TestSchema:
    async def test_all_tables_created(self, engine: AsyncEngine) -> None:
        """Все таблицы из п.46 должны существовать."""
        from sqlalchemy import inspect

        def _tables(conn: object) -> list[str]:
            return sorted(inspect(conn).get_table_names())

        async with engine.connect() as conn:
            tables = await conn.run_sync(_tables)

        expected = {
            "cases", "participants", "case_documents", "document_chunks",
            "case_analyses", "evidence_items", "drafts", "draft_versions",
            "verifications", "law_documents", "court_decisions",
            "judgment_templates", "feedback_samples", "audit_entries",
        }
        assert expected.issubset(set(tables))

    async def test_cascade_delete_works(self, session: AsyncSession) -> None:
        """Удаление дела должно уносить документы (ON DELETE CASCADE).

        Без включённых FK в SQLite cascade не срабатывает — это проверяется
        явно, чтобы регрессия не прошла молча.
        """
        cases = CaseRepository(session)
        docs = DocumentRepository(session)

        case = await cases.create(
            case_number="CASC-001", court_name="Суд", case_type="civil"
        )
        await docs.add(
            CaseDocument(
                case_id=case.id,
                filename="test.pdf",
                document_type=DocumentType.OTHER.value,
                sha256="a" * 64,
                text="текст",
            )
        )
        await session.commit()

        assert await docs.count_for_case(case.id) == 1

        await cases.delete(case.id)
        await session.commit()

        assert await docs.count_for_case(case.id) == 0


class TestCaseRepository:
    async def test_create_and_get(self, session: AsyncSession, case: Case) -> None:
        repo = CaseRepository(session)
        found = await repo.get(case.id)
        assert found is not None
        assert found.case_number == "TEST-001"
        assert found.status == CaseStatus.NEW.value

    async def test_get_by_number(self, session: AsyncSession, case: Case) -> None:
        repo = CaseRepository(session)
        assert (await repo.get_by_number("TEST-001")) is not None
        assert (await repo.get_by_number("НЕТ-ТАКОГО")) is None

    async def test_duplicate_number_detected(self, session: AsyncSession, case: Case) -> None:
        repo = CaseRepository(session)
        assert await repo.get_by_number("TEST-001") is not None

    async def test_list_with_status_filter(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = CaseRepository(session)

        await repo.create(
            case_number="TEST-002", court_name="Суд", case_type="civil",
            status=CaseStatus.DRAFT_READY.value,
        )
        await session.commit()

        all_cases = await repo.list()
        ready = await repo.list(status=CaseStatus.DRAFT_READY.value)
        assert len(all_cases) == 2
        assert len(ready) == 1

    async def test_pagination(self, session: AsyncSession, case: Case) -> None:
        repo = CaseRepository(session)
        for i in range(5):
            await repo.create(
                case_number=f"PAGE-{i}", court_name="Суд", case_type="civil"
            )
        await session.commit()

        page1 = await repo.list(limit=2, offset=0)
        page2 = await repo.list(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2
        assert {c.id for c in page1}.isdisjoint({c.id for c in page2})

    async def test_set_status(self, session: AsyncSession, case: Case) -> None:
        repo = CaseRepository(session)
        updated = await repo.set_status(case.id, CaseStatus.UNDER_REVIEW.value)
        await session.commit()
        assert updated is not None
        assert updated.status == CaseStatus.UNDER_REVIEW.value

    async def test_count(self, session: AsyncSession, case: Case) -> None:
        assert await CaseRepository(session).count() == 1

    async def test_delete_missing_returns_false(self, session: AsyncSession) -> None:
        assert await CaseRepository(session).delete(uuid.uuid4()) is False


class TestDocumentRepository:
    async def test_add_and_list(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = DocumentRepository(session)
        await repo.add(
            CaseDocument(
                case_id=case.id,
                filename="01_claim.pdf",
                document_type=DocumentType.CLAIM.value,
                sha256="b" * 64,
                text="исковое заявление",
            )
        )
        await repo.add(
            CaseDocument(
                case_id=case.id,
                filename="05_protocol.pdf",
                document_type=DocumentType.PROTOCOL.value,
                sha256="c" * 64,
                text="протокол",
            )
        )
        await session.commit()

        docs = await repo.list_for_case(case.id)
        assert len(docs) == 2

        claims = await repo.list_for_case(case.id, document_type=DocumentType.CLAIM.value)
        assert len(claims) == 1
        assert claims[0].filename == "01_claim.pdf"

    async def test_find_by_sha256_detects_duplicate(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = DocumentRepository(session)
        await repo.add(
            CaseDocument(
                case_id=case.id, filename="a.pdf", sha256="d" * 64, text="x"
            )
        )
        await session.commit()
        assert (await repo.find_by_sha256("d" * 64)) is not None
        assert (await repo.find_by_sha256("z" * 64)) is None

    async def test_replace_chunks(self, session: AsyncSession, case: Case) -> None:
        """Пере-чанкинг должен заменять, а не добавлять (Фаза 5)."""
        repo = DocumentRepository(session)
        doc = await repo.add(
            CaseDocument(
                case_id=case.id, filename="long.pdf", sha256="e" * 64, text="текст"
            )
        )
        await session.commit()

        def _chunks(n: int) -> list[DocumentChunk]:
            return [
                DocumentChunk(
                    document_id=doc.id,
                    case_id=case.id,
                    chunk_index=i,
                    text=f"фрагмент {i}",
                    page=1,
                    paragraph=i,
                    character_start=i * 100,
                    character_end=i * 100 + 100,
                    anchor=f"doc:{doc.id}#p{1}#par{i}",
                )
                for i in range(n)
            ]

        async def count_chunks() -> int:
            # Считаем запросом, а не обращением к doc.chunks: relationship
            # с lazy="selectin" вне greenlet вызывает MissingGreenlet.
            result = await session.execute(
                select(func.count()).select_from(DocumentChunk).where(
                    DocumentChunk.document_id == doc.id
                )
            )
            return int(result.scalar_one())

        await repo.replace_chunks(doc.id, _chunks(3))
        await session.commit()
        assert await count_chunks() == 3

        await repo.replace_chunks(doc.id, _chunks(5))
        await session.commit()
        assert await count_chunks() == 5

    async def test_total_text_length(self, session: AsyncSession, case: Case) -> None:
        repo = DocumentRepository(session)
        await repo.add(
            CaseDocument(
                case_id=case.id, filename="a.txt", sha256="f" * 64, text="12345"
            )
        )
        await session.commit()
        assert await repo.total_text_length(case.id) == 5


class TestDocumentTypeExtensibility:
    """П.11: типы должны быть расширяемыми."""

    def test_known_types(self) -> None:
        for value in ("CLAIM", "PROTOCOL", "EXPERT_OPINION"):
            assert DocumentType.is_known(value)

    def test_unknown_type_allowed(self) -> None:
        """Новый тип принимается данными, а не отвергается валидатором."""
        assert DocumentType.is_known("НЕИЗВЕСТНЫЙ_ТИП") is False


class TestAnalysisRepository:
    async def test_upsert_creates_then_updates(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = AnalysisRepository(session)

        first = await repo.upsert(
            case.id, facts=[{"text": "факт 1"}], is_mock=True
        )
        await session.commit()
        assert len(first.facts) == 1

        second = await repo.upsert(case.id, facts=[{"text": "факт 1"}, {"text": "факт 2"}])
        await session.commit()

        assert second.id == first.id
        assert len(second.facts) == 2

    async def test_get_missing_returns_none(
        self, session: AsyncSession, case: Case
    ) -> None:
        assert await AnalysisRepository(session).get(case.id) is None


class TestDraftRepository:
    async def test_add_version_increments(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = DraftRepository(session)
        draft = await repo.create(case.id, status=DraftStatus.DRAFT.value)
        await session.commit()

        v1 = await repo.add_version(draft.id, text="проект 1", author="AI")
        await session.commit()
        assert v1.version == 1
        assert draft.current_version == 1

        v2 = await repo.add_version(
            draft.id, text="проект 2", author="SECRETARY", comment="исправлено"
        )
        await session.commit()
        assert v2.version == 2
        assert draft.current_version == 2

    async def test_versions_preserved_in_order(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = DraftRepository(session)
        draft = await repo.create(case.id)
        await session.commit()

        for i in range(1, 4):
            await repo.add_version(draft.id, text=f"v{i}", author="AI")
        await session.commit()

        versions = await repo.list_versions(draft.id)
        assert [v.version for v in versions] == [1, 2, 3]
        # Полные тексты сохраняются, а не только diff: акт нужно уметь
        # показать в том виде, в каком был принят (п.31).
        assert [v.text for v in versions] == ["v1", "v2", "v3"]

    async def test_get_specific_version(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = DraftRepository(session)
        draft = await repo.create(case.id)
        await session.commit()
        await repo.add_version(draft.id, text="первый", author="AI")
        await session.commit()

        assert (await repo.get_version(draft.id, 1)) is not None
        assert (await repo.get_version(draft.id, 99)) is None

    async def test_add_version_for_missing_draft_raises(
        self, session: AsyncSession
    ) -> None:
        repo = DraftRepository(session)
        with pytest.raises(LookupError):
            await repo.add_version(uuid.uuid4(), text="x", author="AI")

    async def test_add_verification(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = DraftRepository(session)
        draft = await repo.create(case.id)
        await session.commit()

        verification = await repo.add_verification(
            draft.id,
            draft_version=1,
            status=VerificationStatus.REVIEW_REQUIRED.value,
            issues=[{"type": "UNSUPPORTED_CLAIM", "severity": Severity.HIGH.value}],
            claims_checked=5,
            unsupported_claims=1,
        )
        await session.commit()
        assert verification.status == VerificationStatus.REVIEW_REQUIRED.value


class TestAuditRepository:
    async def test_log_and_list(
        self, session: AsyncSession, case: Case
    ) -> None:
        repo = AuditRepository(session)
        await repo.log("case.created", case_id=case.id, actor="tester")
        await repo.log("document.registered", case_id=case.id, actor="tester")
        await session.commit()

        entries = await repo.list_for_case(case.id)
        assert len(entries) == 2
        assert entries[0].action == "document.registered"  # newest first

    async def test_log_without_case(self, session: AsyncSession) -> None:
        repo = AuditRepository(session)
        entry = await repo.log("system.startup")
        await session.commit()
        assert entry.case_id is None


class TestCaseService:
    async def test_create_case(self, session: AsyncSession) -> None:
        service = CaseService(session)
        case = await service.create_case("NEW-1", "Суд", "civil")
        await session.commit()
        assert case.case_number == "NEW-1"
        assert case.status == CaseStatus.NEW.value

    async def test_duplicate_case_number_raises(self, session: AsyncSession) -> None:
        service = CaseService(session)
        await service.create_case("DUP-1", "Суд", "civil")
        await session.commit()

        with pytest.raises(ValueError, match="уже существует"):
            await service.create_case("DUP-1", "Суд", "civil")

    async def test_invalid_status_raises(self, session: AsyncSession) -> None:
        service = CaseService(session)
        case = await service.create_case("ST-1", "Суд", "civil")
        await session.commit()

        with pytest.raises(ValueError, match="Неизвестный статус"):
            await service.set_status(case.id, "ВЫДУМАННЫЙ_СТАТУС")

    async def test_audit_written_on_create(self, session: AsyncSession) -> None:
        """Создание дела должно попадать в аудит (п.46)."""
        service = CaseService(session)
        case = await service.create_case("AUD-1", "Суд", "civil", actor="tester")
        await session.commit()

        entries = await service.audit.list_for_case(case.id)
        assert any(e.action == "case.created" for e in entries)


class TestSessionScope:
    async def test_commit_on_success(self, engine: AsyncEngine) -> None:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_scope(factory) as session:
            await CaseRepository(session).create(
                case_number="SC-1", court_name="Суд", case_type="civil"
            )

        async with factory() as check:
            assert await CaseRepository(check).get_by_number("SC-1") is not None

    async def test_rollback_on_error(self, engine: AsyncEngine) -> None:
        """Ошибка внутри контекста должна откатывать транзакцию."""
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        with pytest.raises(RuntimeError):
            async with session_scope(factory) as session:
                await CaseRepository(session).create(
                    case_number="ROLLBACK-1", court_name="Суд", case_type="civil"
                )
                raise RuntimeError("сбой в середине")

        async with factory() as check:
            assert await CaseRepository(check).get_by_number("ROLLBACK-1") is None


class TestDialectPortability:
    def test_is_sqlite_detects(self) -> None:
        assert is_sqlite("sqlite+aiosqlite:///./x.db") is True
        assert is_sqlite("postgresql+asyncpg://u:p@localhost/db") is False

    async def test_default_url_for_dev_is_sqlite(self) -> None:
        """Без настроенного PostgreSQL разработка должна идти на SQLite.

        Иначе первый запуск на ноутбуке упал бы с ошибкой подключения.
        """
        from app.config import Settings
        from app.db.session import build_database_url

        url = build_database_url(Settings())
        assert is_sqlite(url)

    async def test_postgres_url_built_from_parts(self) -> None:
        """На RTX 3050 URL собирается из POSTGRES_* — единый источник правды."""
        from app.config import Settings
        from app.db.session import build_database_url

        cfg = Settings(
            app_env="runtime",
            postgres_host="db.example",
            postgres_port=5433,
            postgres_db="court",
            postgres_user="u",
            postgres_password="p",
        )
        url = build_database_url(cfg)
        assert "postgresql+asyncpg://u:p@db.example:5433/court" in url
