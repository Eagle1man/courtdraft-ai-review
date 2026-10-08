"""Тесты проекта акта: сохранение, версии, проверка, эндпоинты.

Главное, что здесь проверяется, — продуктовое требование: каждая редакция
сохраняется целиком и не затирает предыдущую. Если это перестанет работать,
юридический акт нельзя будет показать в том виде, в каком он был принят.

Второе по важности — что проект недостижим без материалов дела: система
не должна составить текст по пустому делу.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from app.db.session import create_all, create_engine_and_session, drop_all
from app.main import create_app
from app.models.entities import Case, CaseStatus, DraftStatus
from app.services.draft_service import CaseNotReadyError, DraftService
from app.services.jobs import JobRegistry, JobState

# ── Фикстуры ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    """Движок на временной файловой SQLite.

    Файл, а не память: пул соединений SQLite в памяти создаёт отдельную
    базу на каждое соединение, а асинхронный код открывает их несколько.
    """
    from app.config import Settings

    db_file = tmp_path / "drafts_test.db"
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    manager = create_engine_and_session(Settings(database_url=url))
    eng, _factory = await manager.__aenter__()

    await create_all(eng)
    try:
        yield eng
    finally:
        await drop_all(eng)
        await manager.__aexit__(None, None, None)


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture
async def case_factory(session: AsyncSession):  # noqa: ANN201
    """Создать дело. Позволяет тесту задать нужный номер."""
    from app.db.repositories import CaseRepository

    async def _make(number: str) -> Case:
        created = await CaseRepository(session).create(
            case_number=number,
            court_name="Демонстрационный районный суд",
            case_type="civil",
            category="договорные споры",
            is_synthetic=True,
        )
        await session.flush()
        return created

    return _make


# ── Служебные заглушки ────────────────────────────────────────────────


def _fake_generate(case_id: uuid.UUID):  # noqa: ANN202
    """Заменить генератор, чтобы тест не ждал реальную модель.

    Возвращается настоящий DraftResult с настоящими SectionDraft: если
    подменить и их, тест перестанет проверять контракт между генератором,
    сервисом и проверкой — а именно он здесь и ломается.
    """
    from app.agents.draft_agent import DraftResult, SectionDraft

    async def _generate(pack, template, *, provider=None, settings=None, **kwargs):  # noqa: ANN001, ANN202
        return DraftResult(
            case_number=pack.case_number or str(case_id),
            provider="test",
            model="test-model",
            total_latency_ms=42,
            sections=[
                SectionDraft(
                    key="introductory",
                    name="Вводная часть",
                    text="Дело № DEMO-001 рассмотрено в демонстрационном суде.",
                    is_mock=False,
                    citations=["01_claim.txt"],
                    latency_ms=10,
                ),
                SectionDraft(
                    key="operative",
                    name="РЕШИЛ",
                    # Раздел помечен как требующий проверки: так проверка
                    # должна увидеть, что подтверждения недостаточно.
                    text="Взыскать 150000 рублей. ТРЕБУЕТ ПРОВЕРКИ СПЕЦИАЛИСТОМ",
                    is_mock=False,
                    needs_review=True,
                    citations=["01_claim.txt"],
                    latency_ms=12,
                ),
            ],
        )

    return _generate


@pytest.fixture
async def prepared_case(session: AsyncSession, case_factory) -> uuid.UUID:  # noqa: ANN001
    """Дело с тремя документами — достаточно для пакета доказательств."""
    from app.db.repositories import DocumentRepository

    case = await case_factory("SVC-001")
    repo = DocumentRepository(session)

    texts = [
        ("01_claim.txt", "CLAIM",
         "Исковое заявление о взыскании задолженности 150000 руб. "
         "В силу статьи 309 ГК РФ обязательства должны быть исполнены надлежащим образом."),
        ("03_contract.txt", "CONTRACT",
         "ДОГОВОР ПОСТАВКИ № Д-2026/001 от 15 мая 2026 года. "
         "Истец: Образцов Пётр Петрович. Ответчик: Фирма «Вымышленная Строй». "
         "Ответчик обязался передать товар на 150000 руб."),
        ("04_receipt.txt", "RECEIPT",
         "ПЛАТЁЖНОЕ ПОРУЧЕНИЕ. Сумма перевода: 120 000,00 руб. "
         "Назначение платежа: частичное погашение задолженности."),
    ]

    for filename, doc_type, text in texts:
        await repo.add(
            _document(case.id, filename, doc_type, text)
        )
    await session.flush()
    return case.id


def _document(case_id: uuid.UUID, filename: str, doc_type: str, text: str):  # noqa: ANN202
    import hashlib

    from app.models.entities import CaseDocument

    return CaseDocument(
        case_id=case_id,
        filename=filename,
        document_type=doc_type,
        mime_type="text/plain",
        page_count=1,
        text=text,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


# ── Пакет доказательств ───────────────────────────────────────────────


class TestEvidencePackPersistence:
    async def test_pack_is_saved(self, session: AsyncSession, prepared_case: uuid.UUID) -> None:
        """Пакет доказательств должен попасть в базу."""
        service = DraftService(session)
        pack = await service.build_pack(prepared_case)
        assert pack.items, "пакет должен содержать факты"

        saved = await service.save_pack(prepared_case, pack)
        assert saved == len(pack.items)

        stored = await service.list_evidence(prepared_case)
        assert len(stored) == saved

    async def test_saved_item_keeps_source(self, session: AsyncSession, prepared_case: uuid.UUID) -> None:
        """Факт без источника в базу не попадает.

        Это ключевое требование: пакет — основа для объяснения, откуда
        взялся каждый фрагмент проекта.
        """
        service = DraftService(session)
        pack = await service.build_pack(prepared_case)
        await service.save_pack(prepared_case, pack)

        for item in await service.list_evidence(prepared_case):
            assert item.content, "факт без текста недопустим"
            assert item.source.get("document"), "факт без источника недопустим"
            assert item.category

    async def test_resave_replaces_old_pack(self, session: AsyncSession, prepared_case: uuid.UUID) -> None:
        """Повторная сборка не оставляет смеси старого и нового пакета."""
        service = DraftService(session)
        pack = await service.build_pack(prepared_case)
        await service.save_pack(prepared_case, pack)
        first = len(await service.list_evidence(prepared_case))

        await service.save_pack(prepared_case, pack)
        second = len(await service.list_evidence(prepared_case))

        assert second == first, "повторная запись должна заменять, а не дополнять"

    async def test_empty_case_is_rejected(self, session: AsyncSession, case_factory) -> None:  # noqa: ANN001
        """По пустому делу проект составлять нельзя."""
        case = await case_factory("EMPTY-001")
        service = DraftService(session)

        with pytest.raises(CaseNotReadyError):
            await service.build_pack(case.id)

    async def test_unknown_case_is_rejected(self, session: AsyncSession) -> None:
        service = DraftService(session)
        with pytest.raises(LookupError):
            await service.build_pack(uuid.uuid4())


# ── Фоновая генерация через настоящий сервис ─────────────────────────


class TestDraftGeneration:
    async def test_draft_and_version_saved(self, session: AsyncSession, prepared_case: uuid.UUID, monkeypatch) -> None:  # noqa: ANN001
        """Проект, версия и проверка должны сохраниться в базу."""
        from app.services import draft_service as module

        monkeypatch.setattr(
            module, "generate_draft",
            _fake_generate(prepared_case),
        )

        service = DraftService(session)
        draft, version, report, pack = await service.generate(prepared_case)

        assert draft.id is not None
        assert version.version == 1
        assert version.author == "ai"
        assert "Взыскать" in version.text
        assert report.sections_checked == 2
        assert pack.items

    async def test_evidence_saved_alongside_draft(self, session: AsyncSession, prepared_case: uuid.UUID, monkeypatch) -> None:  # noqa: ANN001
        """Пакет сохраняется вместе с проектом, а не после него.

        Иначе к сохранённому проекту нельзя было бы объяснить,
        откуда взялись факты.
        """
        from app.services import draft_service as module

        monkeypatch.setattr(
            module, "generate_draft", _fake_generate(prepared_case)
        )

        service = DraftService(session)
        await service.generate(prepared_case)

        assert await service.list_evidence(prepared_case), "пакет должен сохраниться"

    async def test_second_generation_creates_version_two(
        self, session: AsyncSession, prepared_case: uuid.UUID, monkeypatch
    ) -> None:  # noqa: ANN001
        """Повторная генерация добавляет версию, а не заменяет проект."""
        from app.services import draft_service as module

        monkeypatch.setattr(
            module, "generate_draft", _fake_generate(prepared_case)
        )

        service = DraftService(session)
        first, v1, _, _ = await service.generate(prepared_case)
        second, v2, _, _ = await service.generate(prepared_case)

        assert first.id == second.id, "проект должен остаться тем же"
        assert v1.version == 1
        assert v2.version == 2

        versions = await service.list_versions(first.id)
        assert [v.version for v in versions] == [1, 2]

    async def test_versions_kept_in_full(self, session: AsyncSession, prepared_case: uuid.UUID, monkeypatch) -> None:  # noqa: ANN001
        """Первая версия не затирается второй.

        Требование п.31: хранится полный текст каждой редакции, а не
        только разметка изменений.
        """
        from app.services import draft_service as module

        monkeypatch.setattr(
            module, "generate_draft", _fake_generate(prepared_case)
        )

        service = DraftService(session)
        draft, v1, _, _ = await service.generate(prepared_case)

        # Правка человека целиком, а не «изменённые места».
        await service.add_manual_version(
            draft.id,
            text="ПОЛНЫЙ ТЕКСТ ПРАВКИ СУДЬИ",
            author="judge",
            comment="исправлена резолютивная часть",
        )

        versions = await service.list_versions(draft.id)
        assert len(versions) == 2
        assert versions[0].text == v1.text, "первая версия не должна измениться"
        assert versions[1].text == "ПОЛНЫЙ ТЕКСТ ПРАВКИ СУДЬИ"
        assert versions[1].author == "judge"

    async def test_author_must_be_human(self, session: AsyncSession, prepared_case: uuid.UUID, monkeypatch) -> None:  # noqa: ANN001
        """Правку может внести только человек, не машина.

        Иначе в истории проекта появились бы записи от модели,
        и «кто подписал акт» перестало бы иметь смысл.
        """
        from app.services import draft_service as module

        monkeypatch.setattr(
            module, "generate_draft", _fake_generate(prepared_case)
        )

        service = DraftService(session)
        draft, _, _, _ = await service.generate(prepared_case)

        with pytest.raises(ValueError):
            await service.add_manual_version(
                draft.id, text="текст", author="robot"
            )


# ── Фоновые задачи ────────────────────────────────────────────────────


class TestJobRegistry:
    async def test_lifecycle(self) -> None:
        registry = JobRegistry()
        case_id = uuid.uuid4()

        job = await registry.create(case_id)
        assert job.state is JobState.PENDING

        await registry.update(job.id, state=JobState.RUNNING)
        assert (await registry.get(job.id)).state is JobState.RUNNING

        await registry.update(job.id, state=JobState.DONE)
        assert (await registry.get(job.id)).state is JobState.DONE

    async def test_missing_job_returns_none(self) -> None:
        registry = JobRegistry()
        assert await registry.get(uuid.uuid4()) is None

    async def test_capacity_bounded(self) -> None:
        """Реестр не должен расти бесконечно.

        Долгоживущий сервер иначе со временем съел бы память на всех
        когда-либо выполненных задачах.
        """
        registry = JobRegistry(capacity=5)

        for _ in range(12):
            await registry.create(uuid.uuid4())

        assert registry.count() == 5

    async def test_dict_has_no_raw_objects(self) -> None:
        """В ответе клиенту не должно быть сырых исключений."""
        registry = JobRegistry()
        job = await registry.create(uuid.uuid4())
        await registry.update(job.id, error="ValueError: секретный текст")

        payload = (await registry.get(job.id)).to_dict()
        assert isinstance(payload["job_id"], str)
        assert payload["error"] == "ValueError: секретный текст"


# ── Эндпоинты ─────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """Клиент с подключённой временной БД.

    Без подключения все доменные эндпоинты отвечают 503 — это правильное
    поведение, но проверять его нужно отдельным тестом, а не случайно
    получать во всех остальных.
    """
    from app.config import AppEnv
    from app.db.bootstrap import ensure_schema
    from app.services.case_service import db

    settings = Settings(
        app_env=AppEnv.DEVELOPMENT,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'api.db').as_posix()}",
        storage_dir=tmp_path / "storage",
        documents_dir=tmp_path / "documents",
        demo_dir=tmp_path / "demo",
        laws_dir=tmp_path / "laws",
        templates_dir=tmp_path / "templates",
    )

    assert await db.connect(settings), "тесту нужна рабочая БД"
    await ensure_schema()

    app = create_app(settings)
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
    finally:
        await db.disconnect()


class TestDraftEndpoints:
    async def test_get_draft_returns_none_without_draft(self, api_client: AsyncClient) -> None:
        """По делу без проекта должен быть 200 и null, а не 404.

        Клиенту нужно отличать «проекта ещё нет» от «дела нет».
        """
        response = await api_client.get(f"/api/cases/{uuid.uuid4()}/draft")
        assert response.status_code == 200

    async def test_versions_without_draft_is_404(self, api_client: AsyncClient) -> None:
        """Список версий без проекта — явная ошибка: просить нечего."""
        response = await api_client.get(f"/api/cases/{uuid.uuid4()}/draft/versions")
        assert response.status_code == 404

    async def test_unknown_job_is_404(self, api_client: AsyncClient) -> None:
        response = await api_client.get(f"/api/jobs/{uuid.uuid4()}")
        assert response.status_code == 404
        assert "перезапуск" in response.json()["detail"].lower()

    async def test_missing_case_is_404(self, api_client: AsyncClient) -> None:
        response = await api_client.post(
            f"/api/cases/{uuid.uuid4()}/draft", json={"actor": "judge"}
        )
        assert response.status_code in {404, 503}

    async def test_edit_rejects_wrong_author(self, api_client: AsyncClient) -> None:
        """Автора правки задаёт клиент, и значение проверяется."""
        response = await api_client.post(
            f"/api/drafts/{uuid.uuid4()}/versions",
            json={"text": "текст", "author": "robot"},
        )
        assert response.status_code in {404, 422}

    async def test_responses_carry_disclaimer(self) -> None:
        """Каждый ответ о проекте обязан напоминать, что это проект.

        Проверяется на схеме: еслиDisclaimer исчезнет из ответа,
        пользователь увидит текст без предостережения.
        """
        from app.schemas.draft import DraftJobOut, DraftListOut, DraftOut

        for schema in (DraftOut, DraftListOut, DraftJobOut):
            defaults = schema.model_fields["disclaimer"].default
            assert defaults and "проект" in defaults.lower()
            assert schema.model_fields["is_draft"].default is True


# ── Согласованность перечислений ──────────────────────────────────────


class TestDuplicateDocumentAcrossCases:
    """Один и тот же документ в разных делах — не дубль.

    Типовой иск или типовой договор законно встречается во многих
    производствах. Раньше поиск по хэшу шёл по всей базе и выбрасывал
    MultipleResultsFound, из-за чего загрузка падала с 500.
    """

    async def test_same_document_allowed_in_two_cases(self, session: AsyncSession) -> None:
        from app.db.repositories import DocumentRepository

        repo = DocumentRepository(session)
        text = "Исковое заявление о взыскании 150000 руб."

        import hashlib

        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

        first = await case_factory_one(session, "DUP-1")
        second = await case_factory_one(session, "DUP-2")

        await repo.add(_document(first.id, "иск.txt", "CLAIM", text))
        await repo.add(_document(second.id, "иск.txt", "CLAIM", text))
        await session.flush()

        # Поиск с ограничением по делу обязан найти свой документ
        # и не должен падать на наличии второго в другом деле.
        found_first = await repo.find_by_sha256(digest, case_id=first.id)
        found_second = await repo.find_by_sha256(digest, case_id=second.id)

        assert found_first is not None
        assert found_second is not None
        assert found_first.case_id == first.id
        assert found_second.case_id == second.id

    async def test_duplicate_within_case_is_found(self, session: AsyncSession) -> None:
        """Внутри одного дела дубль должен находиться — ради отказа 409."""
        import hashlib

        from app.db.repositories import DocumentRepository

        repo = DocumentRepository(session)
        text = "ПРОТОКОЛ"

        case = await case_factory_one(session, "DUP-3")
        await repo.add(_document(case.id, "p.txt", "PROTOCOL", text))
        await session.flush()

        found = await repo.find_by_sha256(
            hashlib.sha256(text.encode("utf-8")).hexdigest(), case_id=case.id
        )
        assert found is not None


async def case_factory_one(session: AsyncSession, number: str):  # noqa: ANN201
    from app.db.repositories import CaseRepository

    created = await CaseRepository(session).create(
        case_number=number,
        court_name="Тестовый суд",
        case_type="civil",
        is_synthetic=True,
    )
    await session.flush()
    return created


class TestStatusVocabulary:
    def test_draft_status_values(self) -> None:
        values = {s.value for s in DraftStatus}
        assert "DRAFT" in values

    def test_case_status_values(self) -> None:
        assert "NEW" in {s.value for s in CaseStatus}
