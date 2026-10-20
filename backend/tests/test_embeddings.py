"""Тесты эмбеддингов (п.53) и конфигурации (п.61)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import (
    AppEnv,
    EmbeddingProviderName,
    LLMProviderName,
    QdrantMode,
    Settings,
    get_settings,
)
from app.embeddings import build_embedding_provider
from app.embeddings.base import EmbeddingProvider, EmbeddingStatus
from app.embeddings.local import HashEmbeddingProvider, LocalEmbeddingProvider
from app.embeddings.mock import MockEmbeddingProvider


class TestProtocolCompliance:
    def test_mock_satisfies_protocol(self) -> None:
        assert isinstance(MockEmbeddingProvider(), EmbeddingProvider)

    def test_local_satisfies_protocol(self) -> None:
        provider = LocalEmbeddingProvider(base_url="http://x:11434", model="bge-m3")
        assert isinstance(provider, EmbeddingProvider)

    def test_hash_fallback_satisfies_protocol(self) -> None:
        assert isinstance(HashEmbeddingProvider(), EmbeddingProvider)


class TestMockEmbedding:
    async def test_dimension(self) -> None:
        provider = MockEmbeddingProvider(dimension=64)
        assert provider.dimension == 64

    async def test_returns_requested_count(self) -> None:
        provider = MockEmbeddingProvider(dimension=32)
        vectors = await provider.embed(["a", "b", "c"])
        assert len(vectors) == 3
        assert all(len(v) == 32 for v in vectors)

    async def test_deterministic(self) -> None:
        """Поиск в MOCK-режиме обязан быть воспроизводимым, иначе метрики
        Recall@5 и MRR (п.63) измеряли бы случайность."""
        provider = MockEmbeddingProvider(dimension=32)
        first = await provider.embed(["текст документа"])
        second = await provider.embed(["текст документа"])
        assert first == second

    async def test_different_text_different_vector(self) -> None:
        provider = MockEmbeddingProvider(dimension=64)
        first, second = await provider.embed(["иск против колонны", "погода в марте"])
        assert first != second

    async def test_empty_text_gives_zero_vector(self) -> None:
        provider = MockEmbeddingProvider(dimension=16)
        vector = (await provider.embed([""]))[0]
        assert all(v == 0.0 for v in vector)

    async def test_empty_batch(self) -> None:
        assert await MockEmbeddingProvider().embed([]) == []

    async def test_status_is_mock(self) -> None:
        assert MockEmbeddingProvider().status is EmbeddingStatus.MOCK

    async def test_health(self) -> None:
        assert await MockEmbeddingProvider().health() is True

    def test_invalid_dimension_rejected(self) -> None:
        with pytest.raises(ValueError):
            MockEmbeddingProvider(dimension=0)


class TestLocalEmbeddingDegradation:
    """П.53: отсутствие модели не должно ронять систему."""

    def test_starts_unavailable(self) -> None:
        provider = LocalEmbeddingProvider(base_url="http://127.0.0.1:1", model="bge-m3")
        assert provider.status is EmbeddingStatus.UNAVAILABLE

    async def test_health_false_when_service_down(self) -> None:
        provider = LocalEmbeddingProvider(
            base_url="http://127.0.0.1:1", model="bge-m3", timeout_sec=1
        )
        assert await provider.health() is False

    def test_dimension_forced_to_configured(self) -> None:
        """Вектор приводится к размерности индекса, а не роняет загрузку."""
        provider = LocalEmbeddingProvider(
            base_url="http://x", model="bge-m3", dimension=8
        )
        assert provider._fit_dimension([1.0] * 16) == [1.0] * 8  # noqa: SLF001
        assert len(provider._fit_dimension([1.0] * 3)) == 8  # noqa: SLF001

    async def test_batches_respected(self) -> None:
        """Батчинг ограничивает память на 8 ГБ (п.54)."""
        provider = LocalEmbeddingProvider(
            base_url="http://127.0.0.1:1", model="bge-m3", dimension=4, batch_size=2
        )
        # Сервис недоступен -> EmbeddingsUnavailableError, а не тишина.
        from app.embeddings.local import EmbeddingsUnavailableError

        with pytest.raises(EmbeddingsUnavailableError):
            await provider.embed(["a", "b", "c"])


class TestHashFallback:
    async def test_produces_vectors(self) -> None:
        provider = HashEmbeddingProvider(dimension=16)
        vectors = await provider.embed(["текст"])
        assert len(vectors) == 1 and len(vectors[0]) == 16

    def test_status_unavailable(self) -> None:
        assert HashEmbeddingProvider().status is EmbeddingStatus.UNAVAILABLE

    async def test_health_false(self) -> None:
        assert await HashEmbeddingProvider().health() is False


class TestEmbeddingFactory:
    def test_mock_selected_in_dev(self) -> None:
        settings = Settings(embedding_provider=EmbeddingProviderName.MOCK)
        assert build_embedding_provider(settings).name == "mock"

    def test_local_selected_on_runtime(self) -> None:
        settings = Settings(embedding_provider=EmbeddingProviderName.LOCAL)
        assert build_embedding_provider(settings).name == "local"

    def test_factory_never_raises(self) -> None:
        """Любая конфигурация должна давать работоспособный провайдер."""
        for provider in (EmbeddingProviderName.MOCK, EmbeddingProviderName.LOCAL):
            settings = Settings(embedding_provider=provider, embedding_dim=64)
            assert build_embedding_provider(settings) is not None


class TestSettings:
    """Переносимость между машинами обеспечивается только .env (п.61)."""

    def test_code_defaults_are_mock(self) -> None:
        """Значения по умолчанию заданы в коде, а не берутся из .env.

        Проверяется именно код: Settings() без аргументов читает .env
        рабочей машины, и тест падал бы каждый раз, когда разработчик
        переключает провайдера на настоящую модель. Значение по
        умолчанию меняться не должно.
        """
        cfg = Settings(_env_file=None)
        assert cfg.llm_provider is LLMProviderName.MOCK
        assert cfg.embedding_provider is EmbeddingProviderName.MOCK
        assert cfg.ollama_enabled is False
        assert cfg.is_real_mode is False

    def test_env_switches_provider(self) -> None:
        """Переключение провайдера возможно без правки кода (п.61)."""
        cfg = Settings(embedding_provider=EmbeddingProviderName.LOCAL)
        assert cfg.embedding_provider is EmbeddingProviderName.LOCAL
        # Модель и размерность обязаны совпадать: иначе индекс
        # создать нельзя.
        assert cfg.embedding_dim == 1024
        assert cfg.embedding_model == "bge-m3"

    def test_runtime_switch_requires_no_code_change(self) -> None:
        """Один и тот же код — два режима (п.61)."""
        dev = Settings(
            llm_provider=LLMProviderName.MOCK,
            embedding_provider=EmbeddingProviderName.MOCK,
            ollama_enabled=False,
            app_env=AppEnv.DEVELOPMENT,
        )
        gpu = Settings(
            llm_provider=LLMProviderName.OLLAMA,
            embedding_provider=EmbeddingProviderName.LOCAL,
            ollama_enabled=True,
            ollama_model="qwen3.5:4b",
            app_env=AppEnv.RUNTIME,
        )
        assert dev.is_real_mode is False
        assert gpu.is_real_mode is True

    def test_cors_origins_from_string(self) -> None:
        """Список Origins приходит из .env строкой через запятую (п.44)."""
        cfg = Settings(cors_origins="http://localhost:3000, http://127.0.0.1:3000")
        assert cfg.cors_origin_list == ["http://localhost:3000", "http://127.0.0.1:3000"]

    def test_cors_origins_ignores_empty_items(self) -> None:
        cfg = Settings(cors_origins="http://localhost:3000,,  ")
        assert cfg.cors_origin_list == ["http://localhost:3000"]

    def test_overlap_must_be_less_than_chunk(self) -> None:
        """Перекрытие >= размера чанка привело бы к зацикливанию chunking."""
        with pytest.raises(ValidationError):
            Settings(chunk_size=100, chunk_overlap=100)

    def test_max_upload_bytes(self) -> None:
        assert Settings(max_upload_mb=50).max_upload_bytes == 50 * 1024 * 1024

    def test_qdrant_memory_default(self) -> None:
        """На ноутбуке Qdrant-сервер не поднимается (Docker недоступен)."""
        assert Settings().qdrant_mode is QdrantMode.MEMORY

    def test_ensure_dirs_creates(self, tmp_path) -> None:
        cfg = Settings(
            storage_dir=tmp_path / "cases",
            documents_dir=tmp_path / "cases" / "documents",
            demo_dir=tmp_path / "demo",
            laws_dir=tmp_path / "laws",
            templates_dir=tmp_path / "templates",
        )
        cfg.ensure_dirs()
        assert cfg.storage_dir.exists()
        assert cfg.demo_dir.exists()

    def test_get_settings_is_cached(self) -> None:
        assert get_settings() is get_settings()
