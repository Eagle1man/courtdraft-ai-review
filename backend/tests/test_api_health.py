"""Тесты API: /api/health, /api/info (п.38, п.58, п.59)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import AppEnv, EmbeddingProviderName, LLMProviderName, Settings
from app.main import create_app
from app.schemas.health import ComponentState


@pytest.fixture
async def client() -> AsyncClient:
    """Клиент поверх ASGI-приложения, без запуска сервера."""
    app = create_app(Settings(app_env=AppEnv.DEVELOPMENT))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


class TestRoot:
    async def test_root_points_to_docs(self, client: AsyncClient) -> None:
        response = await client.get("/")
        assert response.status_code == 200
        assert response.json()["docs"] == "/docs"


class TestHealth:
    async def test_health_returns_200(self, client: AsyncClient) -> None:
        """Health всегда отвечает: клиент должен видеть, ЧТО сломалось."""
        assert (await client.get("/api/health")).status_code == 200

    async def test_reports_backend_ok(self, client: AsyncClient) -> None:
        data = (await client.get("/api/health")).json()
        by_name = {c["name"]: c for c in data["components"]}
        assert by_name["Backend"]["state"] == ComponentState.OK.value

    async def test_ollama_not_required_in_development(self, client: AsyncClient) -> None:
        """П.38/п.57: на ноутбуке отсутствие Ollama — норма, не поломка."""
        data = (await client.get("/api/health")).json()
        by_name = {c["name"]: c for c in data["components"]}
        assert by_name["Ollama"]["state"] == ComponentState.NOT_REQUIRED.value
        assert by_name["Ollama"]["required"] is False

    async def test_gpu_not_required_in_development(self, client: AsyncClient) -> None:
        """П.50: GPU не требуется на DEV."""
        data = (await client.get("/api/health")).json()
        by_name = {c["name"]: c for c in data["components"]}
        assert by_name["GPU"]["state"] == ComponentState.NOT_REQUIRED.value

    async def test_llm_is_mock_in_development(self, client: AsyncClient) -> None:
        data = (await client.get("/api/health")).json()
        by_name = {c["name"]: c for c in data["components"]}
        assert by_name["LLM"]["state"] == ComponentState.MOCK.value
        assert by_name["LLM"]["required"] is False

    async def test_missing_postgres_is_degraded_not_error(self, client: AsyncClient) -> None:
        """PostgreSQL ещё не установлен — это DEGRADED, а не ERROR."""
        data = (await client.get("/api/health")).json()
        assert data["status"] in ("DEGRADED", "OK")

    async def test_summary_is_human_readable(self, client: AsyncClient) -> None:
        """Блок для scripts/health.ps1 (п.59)."""
        data = (await client.get("/api/health")).json()
        assert isinstance(data["summary"], dict)
        assert "Backend" in data["summary"]

    async def test_openapi_available(self, client: AsyncClient) -> None:
        assert (await client.get("/openapi.json")).status_code == 200


class TestInfo:
    async def test_info_reports_mock_mode(self, client: AsyncClient) -> None:
        data = (await client.get("/api/info")).json()
        assert data["llm_provider"] == "mock"
        assert data["embedding_provider"] == "mock"
        assert data["ollama_enabled"] is False

    async def test_info_contains_legal_disclaimer(self, client: AsyncClient) -> None:
        """П.70: предупреждение обязано быть в интерфейсе."""
        data = (await client.get("/api/info")).json()
        disclaimer = data["disclaimer"]
        assert "не осуществляет правосудие" in disclaimer
        assert "проверке и редактированию" in disclaimer


class TestRuntimeMode:
    async def test_runtime_mode_declares_llm_required(self) -> None:
        """На RTX 3050 настоящая модель обязательна (п.38)."""
        app = create_app(
            Settings(
                app_env=AppEnv.RUNTIME,
                llm_provider=LLMProviderName.OLLAMA,
                embedding_provider=EmbeddingProviderName.LOCAL,
                ollama_enabled=True,
                ollama_model="qwen3.5:4b",
            )
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            data = (await test_client.get("/api/health")).json()

        by_name = {c["name"]: c for c in data["components"]}
        # Ollama недоступна в тесте -> UNAVAILABLE и required=True.
        assert by_name["Ollama"]["required"] is True
        assert by_name["GPU"]["required"] is True

    async def test_runtime_ready_endpoint(self) -> None:
        app = create_app(Settings(app_env=AppEnv.RUNTIME, ollama_enabled=True))
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as test_client:
            response = await test_client.get("/api/ready")
        assert response.status_code in (200, 503)
