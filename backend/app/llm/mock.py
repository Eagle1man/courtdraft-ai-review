"""Заглушка LLM для режима разработки без GPU (п.6, п.39, п.69).

Требование ТЗ: mock не должен быть фикцией — он повторяет реальные
интерфейсы. MockLLMProvider реализует тот же LLMProvider, что и OllamaProvider,
поэтому переключение MOCK -> REAL не требует правок в агентах.

Mock детерминирован: одни и те же входные данные дают один и тот же ответ.
Это нужно, чтобы тесты и demo.ps1 были воспроизводимы.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from typing import Any

from app.llm.base import LLMRequest, LLMResponse, LLMUsage

# Признаки того, что модель попросили вернуть JSON.
_JSON_HINTS = ("json", "структур", "список", "объект", "извлеки", "верни")

# Ориентировочная стоимость токена в символах для русского текста.
_CHARS_PER_TOKEN = 2.2


def _estimate_tokens(text: str) -> int:
    """Грубая оценка числа токенов.

    Точная оценка не нужна: счётчик служит для отчётов и метрик,
    а не для биллинга.
    """
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def _stable_hash(text: str) -> int:
    """Стабильный хэш строки (hash() в Python рандомизирован между запусками)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


class MockLLMProvider:
    """Детерминированная заглушка LLM.

    Не выдаёт осмысленный текст — и это правильно: подделка модели не должна
    выглядеть как вывод модели. Вместо этого провайдер делает ровно то, что
    нужно для проверки системы:

    * на запрос JSON возвращает валидный JSON нужной формы;
    * на текстовый запрос возвращает заглушку с явной пометкой MOCK;
    * помечает ответ is_mock=True, чтобы движок проверки знал, что перед ним
      не настоящий вывод модели.
    """

    name = "mock"

    def __init__(self, *, latency_ms: int = 1) -> None:
        # Небольшая задержка — чтобы локальный запуск не выглядел подозрительно
        # мгновенным и не маскировал проблемы с асинхронностью.
        self._latency_ms = max(0, latency_ms)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Сгенерировать детерминированный ответ."""
        started = time.perf_counter()

        if self._latency_ms:
            await asyncio.sleep(self._latency_ms / 1000)

        prompt_text = "\n".join(m.content for m in request.messages)
        text = self._compose(request, prompt_text)

        return LLMResponse(
            text=text,
            usage=LLMUsage(
                prompt_tokens=_estimate_tokens(prompt_text),
                completion_tokens=_estimate_tokens(text),
            ),
            model="mock-llm-v0",
            provider=self.name,
            is_mock=True,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason="stop",
        )

    async def generate_json(
        self,
        request: LLMRequest,
        *,
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Вернуть JSON-заглушку.

        Пытается понять по формулировке задания, какая структура ожидается,
        и вернуть её. Агенерам не нужно знать, MOCK это или нет.
        """
        response = await self.generate(request)
        parsed = self._try_parse(response.text)

        if parsed is not None:
            return parsed

        fallback = self._shape_from_prompt(response.text)
        if fallback is not None:
            return fallback

        return dict(default or {})

    async def health(self) -> bool:
        """Заглушка доступна всегда."""
        return True

    # ── Внутреннее ──────────────────────────────────────────────────────

    def _compose(self, request: LLMRequest, prompt_text: str) -> str:
        """Собрать ответ по типу задания."""
        wants_json = request.json_mode or self._looks_like_json_task(prompt_text)

        if wants_json:
            return self._compose_json(prompt_text)

        return self._compose_text(prompt_text)

    def _looks_like_json_task(self, prompt_text: str) -> bool:
        lowered = prompt_text.lower()
        return any(hint in lowered for hint in _JSON_HINTS)

    def _compose_json(self, prompt_text: str) -> str:
        """JSON-заглушка нужной формы."""
        payload = self._shape_from_prompt(prompt_text) or {"status": "mock"}
        payload["_mock"] = True
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _compose_text(self, prompt_text: str) -> str:
        """Текстовая заглушка с явной пометкой."""
        seed = _stable_hash(prompt_text)
        # Номер, зависящий от входа: один и тот же вопрос — один и тот же номер,
        # разные вопросы — разные. Это позволяет в тестах проверять, что
        # агент действительно реагирует на вход.
        return (
            "[MOCK-ОТВЕТ] Реальная модель не вызывалась (режим LLM_PROVIDER=mock). "
            f"Это заглушка для проверки конвейера. ref={seed % 100000:05d} "
            "Любое утверждение из этого текста не является установленным фактом."
        )

    def _shape_from_prompt(self, prompt_text: str) -> dict[str, Any] | None:
        """Угадать ожидаемую структуру по формулировке задания.

        Эвристика намеренно простая: она должна покрыть запросы агентов,
        а не быть универсальным парсером.
        """
        lowered = prompt_text.lower()

        if "участник" in lowered:
            return {"participants": [], "claims": [], "evidence": [], "important_dates": []}
        if "факт" in lowered or "analysis" in lowered or "анализ" in lowered:
            return {
                "facts": [],
                "claims": [],
                "objections": [],
                "evidence": [],
                "procedural_history": [],
                "disputed_facts": [],
                "established_facts": [],
                "unresolved_questions": [],
            }
        if "норм" in lowered or "law" in lowered or "стать" in lowered:
            return {"laws": [], "unresolved": []}
        if "практик" in lowered or "practice" in lowered or "прецедент" in lowered:
            return {"cases": [], "similarity": []}
        if "доказательств" in lowered or "evidence" in lowered:
            return {"matrix": [], "unproven_facts": []}
        if "провер" in lowered or "верифик" in lowered or "verif" in lowered:
            return {"status": "REVIEW_REQUIRED", "issues": []}
        if "проект" in lowered or "draft" in lowered or "решени" in lowered:
            return {"sections": {}, "draft_text": ""}
        if "протокол" in lowered or "transcript" in lowered:
            return {
                "participants": [],
                "statements": [],
                "motions": [],
                "evidence_examined": [],
                "procedural_actions": [],
            }
        return None

    def _try_parse(self, text: str) -> dict[str, Any] | None:
        """Разобрать JSON из ответа модели, терпимо к обёрткам (```json ...)."""
        candidate = text.strip()

        fenced = re.search(r"```(?:json)?\s*(.+?)```", candidate, re.DOTALL)
        if fenced:
            candidate = fenced.group(1).strip()

        # Модель могла добавить текст вокруг JSON — берём самый широкий блок.
        block = re.search(r"\{.*\}", candidate, re.DOTALL)
        if block:
            candidate = block.group(0)

        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            return None

        return parsed if isinstance(parsed, dict) else None
