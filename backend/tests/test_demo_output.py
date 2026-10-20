"""Тест: демо не теряет предыдущий результат при сбое.

Дефект найден на живом прогоне. Демо очищало каталог вывода перед
работой, поэтому любой сбой на промежуточном шаге — например,
недоступная модель эмбеддингов — оставлял каталог пустым: старый
проект стёрт, новый не дописан. Демонстрация теряла ровно тот
материал, ради которого запускалась.

Тест проверяет именно следствие: после уборки предыдущий результат
должен лежать в .previous, а не исчезнуть.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import demo as demo_module  # noqa: E402


@pytest.fixture
def output_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Подменённый каталог вывода."""
    target = tmp_path / "output"
    monkeypatch.setattr(demo_module, "OUTPUT_DIR", target)
    return target


class TestPreviousResultPreserved:
    def test_previous_draft_survives_reset(
        self, output_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Главное: старый проект не пропадает."""
        importlib.reload(demo_module)
        monkeypatch.setattr(demo_module, "OUTPUT_DIR", output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "draft.md").write_text("старый проект", encoding="utf-8")

        demo_module.reset_output()

        previous = output_dir / ".previous"
        assert previous.exists(), "предыдущий результат не сохранён"
        assert (previous / "draft.md").exists()
        assert (previous / "draft.md").read_text(encoding="utf-8") == "старый проект"

    def test_output_cleared_for_new_run(
        self, output_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """При этом каталог вывода чист — повторный запуск воспроизводим."""
        importlib.reload(demo_module)
        monkeypatch.setattr(demo_module, "OUTPUT_DIR", output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "draft.md").write_text("старый", encoding="utf-8")

        demo_module.reset_output()

        assert not (output_dir / "draft.md").exists()

    def test_only_one_generation_kept(
        self, output_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Бэкап не копится: при каждом запуске прошлое затирается.

        Без ограничения каталог рос бы бесконечно, что для демонстрации
        не нужно: нужен ровно один предыдущий прогон.
        """
        importlib.reload(demo_module)
        monkeypatch.setattr(demo_module, "OUTPUT_DIR", output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "draft.md").write_text("первый", encoding="utf-8")
        demo_module.reset_output()

        (output_dir / "draft.md").write_text("второй", encoding="utf-8")
        demo_module.reset_output()

        previous = output_dir / ".previous"
        names = sorted(p.name for p in previous.iterdir())
        assert names.count("draft.md") == 1
        assert (previous / "draft.md").read_text(encoding="utf-8") == "второй"

    def test_busy_file_does_not_crash(
        self, output_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Занятый файл не роняет демо."""
        importlib.reload(demo_module)
        monkeypatch.setattr(demo_module, "OUTPUT_DIR", output_dir)
        monkeypatch.setattr(demo_module, "say", lambda *a, **k: None)

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "locked.md").write_text("занятый", encoding="utf-8")

        def refuse(*args: object, **kwargs: object) -> None:
            raise PermissionError("файл занят")

        monkeypatch.setattr(demo_module.shutil, "move", refuse)

        demo_module.reset_output()  # не должно бросить исключение
        assert output_dir.exists()
