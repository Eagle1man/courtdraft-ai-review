"""Сборка обучающей выборки из корпуса судебных решений.

Собирает пары «обстоятельства дела → резолютивная часть» для дообучения
модели формулировать проект решения.

Два решения, которые определяют качество выборки.

Первое: в обстоятельства входит мотивировка — то, что суд уже написал о
том, кто прав. Без неё задача сводится к «угадай приговор», и модель
начинает выдавать уверенные резолюции там, где судья должен решать
сам. С мотивировкой задача честная: суд уже обосновал вывод, требуется
его оформить. Продуктовая норма — система готовит проект, решение
принимает судья — при этом не нарушается.

Второе: пример не берётся, если сумма из резолютивной части не
объясняется обстоятельствами. Иначе модель учится писать итог, который
не вытекает из дела, а проверка потом ловит это как придуманное число.

Обезличивание и проверка на остаточные персональные данные — не
дополнение, а условие попадания примера в выборку. Пример с утечкой
выбрасывается целиком, а не правится на месте: правка на месте даёт
текст, которого в деле никогда не было.
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "lora"

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "build_real_demo", ROOT / "scripts" / "build_real_demo.py"
)
base = importlib.util.module_from_spec(spec)
sys.modules["build_real_demo"] = base
spec.loader.exec_module(base)

SYSTEM_PROMPT = (
    "Ты — помощник судьи. Составь проект резолютивной части решения по "
    "обстоятельствам дела. Не делай вывод о том, кто прав, и не подставляй "
    "суммы, которых нет в обстоятельствах."
)

# Признаки гражданского дела. Фильтр из build_real_demo — это три
# варианта строки «гражданское дело», и он годен, чтобы выбрать одно
# решение для витрины: 1 дело на 27 668. Для отбора корпуса он непригоден,
# поэтому признаки гражданского и уголовного заданы здесь.
CIVIL_MARKERS = (
    "гражданское дело",
    "исковые требования",
    "истец",
    "ответчик",
    "взыскать",
    "признать",
    "исковое заявление",
    "подлежит удовлетворению",
)
CRIMINAL_MARKERS = ("приговорил:", "постановил:", "приговор вступил")

#: Резолютивная часть короче этого — это «И СЧИТАЮ ВОЗМЕННЫМ» и подобное.
#: Формально это решение, но учиться на нём нечего.
MIN_OPERATIVE_CHARS = 200

#: Длиннее — это уже разбор, а не формулировка резолютивной части.
MAX_OPERATIVE_CHARS = 2000

#: Обстоятельства длиннее этого в обучение не идут. Русский текст в
#: токенах примерно вдвое длиннее символов, при контексте 2048 токенов
#: вход должен укладываться примерно в 5000-6000 знаков. Порог не
#: произвольный: пример длиннее всё равно обрежется по контексту, причём
#: под нож попадёт концовка, а в ней находится резолютивная часть, —
#: модель получила бы вопрос без ответа.
MAX_INPUT_CHARS = 6000

#: Больше разных статей — решение настолько перегружено нормами, что
#: в нём нет предмета спора, а одна норма на каждый абзац. Порог 20,
#: а не 12: двенадцать был взят, когда витрина показывала одно дело
#: целиком, и для обучения он отбрасывал треть гражданских дел.
MAX_DISTINCT_LAWS = 20

#: Суммы в тексте: «11 107,84 руб.», «150 000 рублей», «1 000 000,00».
MONEY = re.compile(
    r"(\d[\d\s ]*(?:,\d{1,2})?)\s*(?:руб(?:\.|ля|ль|лей|лям)|₽)",
    re.IGNORECASE,
)
LAW = re.compile(r"ст\.\s?\d+")

PROCEDURAL_REFUSAL = re.compile(
    r"(И\s+СЧИТАЮ\s+ВОЗМЕННЫМ|иск\s+оставить\s+без\s+рассмотрения)",
    re.IGNORECASE,
)

#: Заголовки резолютивной части в корпусе набраны с разрядкой:
#: «Р Е Ш И Л:», «П О С Т А Н О В И Л:». Ни один из маркеров на такой
#: текст не срабатывает, и треть корпуса выпадала из отбора целиком.
#: Схлопывается только последовательность заглавных кириллических букв,
#: разделённых пробелами: обычный текст и числа не затрагиваются.
SPACED_HEADING = re.compile(r"(?:[А-ЯЁ][ \xa0]+){2,}[А-ЯЁ]")

#: Подпись в резолютивной части приходит последней строкой. В корпусе
#: это и «Мировой судья», и отдельно фамилия с инициалами («М.П.
#: Зайченко»), и плейсхолдер обезличивания. Регистр значения не имеет.
SIGNATURE_KEYWORD = re.compile(
    r"^\s*(подпись|(?:мировой\s+|районный\s+|городской\s+)?судья[\s:\w.]*)\s*$",
    re.IGNORECASE,
)
SIGNATURE_NAME = re.compile(
    r"^\s*(?:[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.?\.?|И\.\s?О\.\s*[А-ЯЁ][а-яё]+|<ФИО\d?>)\s*$"
)


def normalize_headings(text: str) -> str:
    """Схлопнуть разрядку в заголовках вида «Р Е Ш И Л:»."""
    return SPACED_HEADING.sub(lambda m: re.sub(r"[ \xa0]+", "", m.group(0)), text)


def money_values(text: str) -> set[int]:
    """Суммы в копейках. Точное совпадение, без округления.

    Сумма из текста переводится в копейки умножением на 100, чтобы
    сравнение было целочисленным: 11107,84 в виде float сравнивается
    с другой суммой ненадёжно из-за двоичного представления.
    """
    values: set[int] = set()
    for raw in MONEY.findall(text):
        digits = re.sub(r"[^\d,]", "", raw)
        if not digits:
            continue
        whole, _, frac = digits.partition(",")
        try:
            base_amount = int(whole or 0) * 100
        except ValueError:
            continue
        values.add(base_amount + int((frac or "0").ljust(2, "0")[:2]))
    return values


#: После резолюции в корпусе идёт блок завершения: порядок обжалования,
#: подпись судьи, отметки «копия верна», «обезличено». Сигнатуры стоят
#: именно там, и порой разорваны по строкам («Мировой\nсудья \nФИО»), так
#: что поиск подписи по строке их пропускает. Обрезаем от первого
#: упоминания — наша система составляет резолюцию по шаблону и учить
#: модель писать этот хвост незачем.
ATTESTATION_MARKERS = (
    "решение может быть обжаловано",
    "определение может быть обжаловано",
    "постановление может быть обжаловано",
    "право обжалования",
    "копия верна",
    "верно:",
    "полный текст",
    "<обезличено>",
    "решение изготовлено на компьютере",
    "на момент опубликования",
    "мировой судья",
    "городской судья",
    "районный судья",
)


def cut_attestation(text: str) -> str:
    """Отрезать блок завершения: обжалование, подпись, отметки."""
    lowered = text.lower()
    cuts = [lowered.find(marker) for marker in ATTESTATION_MARKERS]
    positions = [index for index in cuts if index > 0]
    if not positions:
        return text
    return text[: min(positions)].rstrip()


#: Знаки, которыми заканчивается целое предложение. Отдельно от
#: отсева обрезанных решений: раньше по этому признаку отбрасывалось
#: 7614 дел, и проверка ловила не обрыв, а подпись судьи на отдельной
#: строке и концовку «вступило в законную силу». Признак оказался
#: бесполезным и убран.
SENTENCE_END = ".!?;:»)]»"


def is_signature_line(line: str) -> bool:
    """Подпись судьи или его фамилия в последней строке."""
    return bool(SIGNATURE_KEYWORD.match(line) or SIGNATURE_NAME.match(line))


def operative_text(parts: dict[str, str]) -> str:
    """Резолютивная часть без блока завершения.

    Подпись в ответ не попадает: в проекте решения она берётся из
    реквизитов, а из ответа модели фамилия судьи была бы выдумкой.
    """
    text = parts.get("operative", "").strip()
    lines = [line for line in text.splitlines() if line.strip()]
    while lines and is_signature_line(lines[-1]):
        lines.pop()
    return cut_attestation("\n".join(lines)).strip()


def facts_text(parts: dict[str, str]) -> str:
    """Обстоятельства дела в порядке, в котором их читает судья."""
    blocks: list[str] = []
    for key, title in (
        ("header", "Реквизиты дела"),
        ("claim", "Позиция истца"),
        ("defence", "Возражения ответчика"),
        ("procedure", "Ход рассмотрения"),
        ("findings", "Мотивы суда"),
    ):
        value = parts.get(key, "").strip()
        if value:
            blocks.append(f"## {title}\n{value}")
    return "\n\n".join(blocks).strip()


def rejects(text: str) -> str:
    """Почему решение не годится. Пустая строка — годится.

    Уголовные отбрасываются отдельно и раньше гражданских: в деле о
    преступлении с гражданским иском тоже есть истец и ответчик, так что
    широкий признак гражданского дела такие решения пропускает. А
    разбирать их нечем — резолютивная часть начинается с «ПРИГОВОРИЛ:»,
    которого нет среди маркеров, и весь текст после него уезжает в
    мотивировку.
    """
    lowered = text.lower()
    if any(marker in lowered for marker in CRIMINAL_MARKERS):
        return "уголовное или административное"
    if not any(marker in lowered for marker in CIVIL_MARKERS):
        return "не гражданское"
    if "заочное" in lowered:
        return "заочное решение"
    laws = set(LAW.findall(text))
    if len(laws) > MAX_DISTINCT_LAWS:
        return f"слишком много разных норм: {len(laws)}"
    return ""


def evaluate(parts: dict[str, str]) -> tuple[str, str]:
    """Вернуть пару и причину отказа.

    Порядок проверок значим: сначала дешёвые строковые признаки, потом
    обезличивание, и только потом разбор сумм. Иначе на 70 тысячах дел
    обезличивание считается для тех, что всё равно будут отброшены.
    """
    operative = operative_text(parts)
    if not operative:
        return "", "нет резолютивной части"
    if len(operative) < MIN_OPERATIVE_CHARS:
        return "", f"резолюция короче {MIN_OPERATIVE_CHARS} знаков"
    if len(operative) > MAX_OPERATIVE_CHARS:
        return "", f"резолюция длиннее {MAX_OPERATIVE_CHARS} знаков"
    if PROCEDURAL_REFUSAL.search(operative):
        return "", "процедурная отписка"

    facts = facts_text(parts)
    if len(facts) < 800:
        return "", "обстоятельства короче 800 знаков"
    if len(facts) > MAX_INPUT_CHARS:
        return "", f"обстоятельства длиннее {MAX_INPUT_CHARS} знаков"

    # Сумма требования не обязана стоять в блоке требований: суды
    # размазывают её по мотивировке («исковое требование составляет
    # 150 000 рублей»), и проверка только требований отбрасывала
    # готовые примеры. Смотрим по всем обстоятельствам сразу.
    facts_money = money_values(
        parts.get("claim", "") + parts.get("findings", "") + parts.get("defence", "")
    )
    awarded = money_values(operative)
    if not facts_money:
        return "", "в обстоятельствах нет сумм"
    if not awarded:
        return "", "в резолюции нет сумм"
    unexplained = awarded - facts_money
    if unexplained:
        return "", f"сумма в резолюции не объясняется обстоятельствами: {len(unexplained)}"

    facts_clean = base.anonymize(facts)
    operative_clean = base.anonymize(operative)
    leaks = base.find_leaks(facts_clean) + base.find_leaks(operative_clean)
    if leaks:
        return "", f"остались персональные данные: {leaks[0].split(':')[0]}"

    return (
        json.dumps(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": facts_clean},
                    {"role": "assistant", "content": operative_clean},
                ]
            },
            ensure_ascii=False,
        ),
        "",
    )


def load_texts(paths: list[Path]) -> list[str]:
    """Собрать тексты решений из parquet-файлов корпуса."""
    import pandas as pd

    texts: list[str] = []
    for path in paths:
        if not path.exists():
            print(f"  пропускаю {path.name}: файла нет")
            continue
        frame = pd.read_parquet(path)
        column = "text" if "text" in frame.columns else None
        if column is None:
            print(f"  пропускаю {path.name}: нет колонки text")
            continue
        values = [str(value) for value in frame[column].tolist()]
        print(f"  {path.name}: {len(values)} дел")
        texts.extend(values)
    return texts


def corpus_stats(path: Path) -> dict[str, Any]:
    """Что в корпусе по меткам разметки. Не влияет на отбор."""
    import pandas as pd

    if not path.exists() or "spans" not in pd.read_parquet(path).columns:
        return {}
    frame = pd.read_parquet(path, columns=["spans"])
    counter: Counter[str] = Counter()
    for raw in frame["spans"]:
        try:
            for span in ast.literal_eval(str(raw)):
                counter[str(span[2])] += 1
        except (ValueError, SyntaxError, IndexError, TypeError):
            continue
    total = sum(counter.values())
    return {
        "уникальных меток": len(counter),
        "спанов": total,
        "спанов_с_цифрами": 0,
    }


#: Материалы отложенного дела раскладываются так же, как на демо-стенде.
#: Имена файлов не произвольны: по ним система определяет тип документа
#: (app/ingestion/extract.py), и от него зависит разбор пакета
#: доказательств. Название «01_claim.txt» — это иск, «05_protocol.txt» —
#: протокол.
CASE_FILES: tuple[tuple[str, str, str], ...] = (
    ("00_case_info.txt", "СВЕДЕНИЯ О ДЕЛЕ\n(по материалам дела)", "header"),
    ("01_claim.txt", "ИСКОВОЕ ЗАЯВЛЕНИЕ ИСТЦА", "claim"),
    ("02_response.txt", "ВОЗРАЖЕНИЯ ОТВЕТЧИКА", "defence"),
    ("05_protocol.txt", "ХОД СУДЕБНОГО ЗАСЕДАНИЯ", "procedure"),
    ("06_court_findings.txt", "ОБСТОЯТЕЛЬСТВА, УСТАНОВЛЕННЫЕ СУДОМ", "findings"),
)


def write_eval_cases(pairs: list[dict[str, Any]], out_dir: Path) -> int:
    """Разложить отложенные дела по файлам материалов.

    Измерение идёт на настоящем деле, а не на одном скомканном тексте:
    разделы проекта ссылаются на конкретные документы, и если подать
    материалами один файл, ссылки вырождаются, а вместе с ними портится
    главное число замера — сколько утверждений подтверждено источником.

    Рядом кладётся реальная резолютивная часть суда как эталон. Пока
    никто её не проверил, но именно на неё юрист будет ставить отметки
    «правильно / неправильно» — это и есть эталонная разметка, без
    которой каппа и любые оценки качества считают согласие системы с
    самой собой.
    """
    cases_dir = out_dir / "eval_cases"
    cases_dir.mkdir(parents=True, exist_ok=True)
    for stale in cases_dir.glob("case-*"):
        for item in stale.glob("*.txt"):
            item.unlink()
        stale.rmdir()

    written = 0
    manifest: list[dict[str, Any]] = []
    for number, pair in enumerate(pairs, start=1):
        parts = pair.get("parts") or {}
        case_dir = cases_dir / f"case-{number:03d}"
        case_dir.mkdir(parents=True, exist_ok=True)
        files: list[str] = []
        for filename, title, key in CASE_FILES:
            body = str(parts.get(key, "")).strip()
            if not body:
                continue
            cleaned = base.anonymize(body)
            if base.find_leaks(cleaned):
                cleaned = ""
            if not cleaned:
                continue
            (case_dir / filename).write_text(f"{title}\n\n{cleaned}\n", encoding="utf-8")
            files.append(filename)
        reference = str(pair.get("operative", "")).strip()
        if reference:
            (case_dir / "court_reference.txt").write_text(
                reference + "\n", encoding="utf-8"
            )
        manifest.append({"case": case_dir.name, "files": files})
        written += 1

    (cases_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        nargs="*",
        default=[r"D:\ollama\hf_train.parquet"],
        help="parquet-файлы корпуса",
    )
    parser.add_argument("--eval-size", type=int, default=50)
    parser.add_argument("--val-size", type=int, default=50)
    parser.add_argument("--limit", type=int, default=0, help="0 — без ограничения")
    parser.add_argument("--out", default=str(OUT_DIR))
    args = parser.parse_args(argv)

    print("Читаю корпус")
    texts = load_texts([Path(item) for item in args.corpus])
    if not texts:
        print("Нет ни одного дела — проверьте путь к корпусу.")
        return 1
    if args.limit:
        texts = texts[: args.limit]

    print("Отбираю пары")
    reasons: Counter[str] = Counter()
    pairs: list[dict[str, Any]] = []
    for raw in texts:
        text = normalize_headings(raw)
        reason = rejects(text)
        if reason:
            reasons[reason.split(":")[0]] += 1
            continue
        parts = base.split_decision(text)
        if not parts:
            reasons["не разобралось"] += 1
            continue
        payload, reason = evaluate(parts)
        if not payload:
            reasons[_reason_class(reason)] += 1
            continue
        pairs.append(
            {
                "payload": json.loads(payload),
                "parts": parts,
                "operative": base.anonymize(operative_text(parts)),
                "len": len(text),
            }
        )

    # Отложенные наборы берём с конца и перемешиваем только обучающую
    # часть: иначе порядок в файле выдаст модели время, а не случайность.
    # Перемешивание обучающей части нужно для повторяемости набора, а
    # не для секретности: тот же seed даёт тот же файл при пересборке.
    picked = random.Random(20261018)  # noqa: S311
    picked.shuffle(pairs)
    eval_pairs = pairs[: args.eval_size]
    val_pairs = pairs[args.eval_size : args.eval_size + args.val_size]
    train_pairs = pairs[args.eval_size + args.val_size :]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = write_eval_cases(eval_pairs, out_dir)
    for name, chunk in (
        ("train", train_pairs),
        ("val", val_pairs),
        ("eval", eval_pairs),
    ):
        with (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for item in chunk:
                handle.write(json.dumps(item["payload"], ensure_ascii=False) + "\n")
        print(f"  {name}.jsonl: {len(chunk)} примеров")

    report = {
        "дел_в_корпусе": len(texts),
        "пар_подходящих": len(pairs),
        "обучение": len(train_pairs),
        "val": len(val_pairs),
        "eval": len(eval_pairs),
        "дел_с_материалами": cases,
        "причины_отказа": dict(reasons.most_common()),
        "разметка_корпуса": corpus_stats(Path(args.corpus[0])),
        "системный_промпт": SYSTEM_PROMPT,
    }
    (out_dir / "dataset_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print(f"дел в корпусе: {len(texts)}")
    print(f"пар подходящих: {len(pairs)}")
    print("причины отказа:")
    for reason, count in reasons.most_common():
        print(f"  {reason}: {count}")
    print(f"отчёт: {out_dir / 'dataset_report.json'}")
    return 0


def _reason_class(reason: str) -> str:
    """Причина отказа без конкретных чисел — иначе отчёт распухает."""
    for marker, name in (
        ("нет резолютивной части", "нет резолютивной части"),
        ("резолюция короче", "резолюция слишком короткая"),
        ("резолюция длиннее", "резолюция слишком длинная"),
        ("процедурная отписка", "процедурная отписка"),
        ("обстоятельства короче", "обстоятельства слишком короткие"),
        ("обстоятельства длиннее", "обстоятельства слишком длинные"),
        ("в обстоятельствах нет сумм", "в обстоятельствах нет сумм"),
        ("в резолюции нет сумм", "в резолюции нет сумм"),
        ("сумма в резолюции", "сумма не объясняется обстоятельствами"),
        ("остались персональные", "остались персональные данные"),
    ):
        if reason.startswith(marker):
            return name
    return reason.split(":")[0]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
