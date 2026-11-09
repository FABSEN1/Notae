r"""Notae — сборка презентации из файла сценария.

Запуск:  python build.py   (или двойной клик)

Скрипт сам находит файл сценария (txt / doc / docx / md / tex) в своей папке,
рендерит слайды и склеивает их в цельное видео.

Результат:
  media/slides/Title.mp4 (если есть титульный слайд)
  media/slides/Slide01.mp4, Slide02.mp4, ...
  media/final.mp4

Имена слайдов сквозные: Title, затем Slide01, Slide02, ... (с единицы).
Они же печатаются в терминале и используются в проверках сценария.

Полное описание формата сценария и возможностей — в README.md.
"""

import inspect
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

# Консоль Windows часто работает в cp1251. Заменяем непечатаемые символы
# (например, диакритику в названии сцены), чтобы отчёт не падал.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, OSError):
        pass

# ─────────────────────────────────────────────────────────────────────────────
# 1. НАСТРОЙКИ
# ─────────────────────────────────────────────────────────────────────────────
QUALITY = "-qh"                 # 1920×1080
FPS = 30
MAX_PARALLEL = 5                # одновременно рендерится не более 5 слайдов
GENERATED = "_scenes.py"

HERE = Path(__file__).resolve().parent
MEDIA = HERE / "media"
SLIDES_DIR = MEDIA / "slides"
FINAL = MEDIA / "final.mp4"
HANDOUT_TEX = MEDIA / "handout.tex"
HANDOUT_PDF = MEDIA / "handout.pdf"
WORK_DIR = HERE / "_work"

SCENARIO_EXTS = (".txt", ".docx", ".doc", ".md", ".tex")

# ── Геометрия слайда ─────────────────────────────────────────────────────────
# Кадр видео — 16:9. Его физическая ширина принята такой же, как у PDF-страницы
# (36.1 см), поля слева и справа — по 2 см. Поэтому текст занимает
# (36.1 − 2·2) / 36.1 ширины кадра. Ширина кадра Manim — 14.222222 ед.
SLIDE_WIDTH_CM = 36.1
MARGIN_X_CM = 2.0
FRAME_WIDTH_UNITS = 14.222222
FRAME_HEIGHT_UNITS = 8.0
MAX_LINE_WIDTH_UNITS = (
    (SLIDE_WIDTH_CM - 2 * MARGIN_X_CM) / SLIDE_WIDTH_CM * FRAME_WIDTH_UNITS
)
# В Manim TeX компилируется в 10 pt, а затем масштабируется в font_size/48 раз.
# Измерено: при font_size=48 линейка \rule{1cm} занимает 1.4173 ед. Manim.
# Значит, 1 pt TeX при font_size=48 — это 0.049814 ед., а при размере s —
# 0.049814·s/48 ед. Отсюда ширина \parbox в pt для нужной ширины в ед.
TEX_UNITS_PER_PT_AT_48 = 1.41733 / 28.452756
MAX_LINE_WIDTH_PT_AT_36 = (
    MAX_LINE_WIDTH_UNITS / (TEX_UNITS_PER_PT_AT_48 * 36.0 / 48.0)
)

# Порядок типов в отчёте (сначала LaTeX, потом оформление).
ISSUE_ORDER = {"latex": 0, "sub": 1, "wrap": 2, "width": 3, "overflow": 4}

# ─────────────────────────────────────────────────────────────────────────────
# 2. ТЕМА: палитра, LaTeX-преамбула, размеры
# ─────────────────────────────────────────────────────────────────────────────
BG = "#121417"
TEXT = "#E9E6E1"
MUTED = "#A7A39C"
YELLOW = "#FFD166"      # яркий жёлтый (заголовок)
GOLD = "#E3B56B"
BLUE = "#7FB3D5"
GREEN = "#8FBF8F"
RED = "#D9827A"
PURPLE = "#B49ACB"

PALETTE = {
    "BG": BG, "TEXT": TEXT, "MUTED": MUTED, "YELLOW": YELLOW,
    "GOLD": GOLD, "BLUE": BLUE, "GREEN": GREEN, "RED": RED, "PURPLE": PURPLE,
}

TITLE = 44
BODY = 36
SUB = 26

# Те же правила «это формула или текст», что и в Slide._prepare (для PDF).
MATH_ENVS = {"aligned", "align", "align*", "gather", "gather*", "split",
             "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix",
             "Vmatrix", "cases", "array", "eqnarray", "eqnarray*",
             "multline", "multline*"}
TEXT_HINTS = ("\\begin{", "\\vspace", "\\hspace", "\\vskip", "\\hskip",
              "\\textbf", "\\textit", "\\emph", "\\underline",
              "\\noindent", "\\centering", "\\par", "\\newline", "\\\\",
              "\\hfill", "\\vfill", "\\rule", "\\includegraphics",
              "\\texttt", "\\textsf", "\\textrm", "\\textsc")

# Базовые пакеты (PT Serif — векторный шрифт с полной кириллицей).
BASE_PREAMBLE = [
    r"\usepackage[utf8]{inputenc}",
    r"\usepackage[T2A]{fontenc}",
    r"\usepackage[english,russian]{babel}",
    r"\usepackage{PTSerif}",
    r"\usepackage{amsmath}",
    r"\usepackage{amssymb}",
    r"\usepackage{amsfonts}",
    r"\usepackage{amsthm}",
    r"\usepackage{xcolor}",
]
BASE_NAMES = {"inputenc", "fontenc", "babel", "ptserif",
              "amsmath", "amssymb", "amsfonts", "amsthm", "xcolor"}

# Окружения-теоремы, которые заводим по умолчанию (если не определены в сценарии).
DEFAULT_THEOREMS = [
    ("theorem", "Теорема"),
    ("lemma", "Лемма"),
    ("definition", "Определение"),
    ("corollary", "Следствие"),
    ("proposition", "Утверждение"),
    ("remark", "Замечание"),
    ("example", "Пример"),
]


def resolve_color(v: str) -> str:
    v = v.strip()
    return PALETTE.get(v, v if v.startswith("#") else v)


# ─────────────────────────────────────────────────────────────────────────────
# 2b. ОБЩИЕ ПРАВИЛА ДЛЯ ТЕКСТА, ФОРМУЛ И ОТБИВОК
# ─────────────────────────────────────────────────────────────────────────────
def prepare_line_tex(tex: str) -> str:
    """Решить, как набирать содержимое строки: как текст или как формулу.

    Правило не зависит от языка и от того, какой babel указан в сценарии:

    * если в строке есть буквы за пределами ASCII (кириллица, латиница с
      диакритикой, другие алфавиты) — это текст;
    * если в строке есть обычные латинские слова — это текст (английский
      текст больше не превращается в формулу);
    * если строка состоит из математических команд/символов — это формула.

    Явные ``$...$`` и ``\\[...\\]`` сохраняются как есть.
    """
    if not tex.strip():
        return tex

    # --- 1. Любые «нелатинские» буквы: кириллица, é, ñ, ü и т.п. ---
    #     Комбинируемые диакритические знаки (U+0301 и т.п.) тоже считаем
    #     текстом: они осмысленны только вместе с буквой.
    for ch in tex:
        if ord(ch) > 127:
            cat = unicodedata.category(ch)
            if cat.startswith("L") or cat.startswith("M"):
                return tex

    t = tex.replace("$", "")

    # --- 2. Математические окружения ---
    envs = re.findall(r"\\begin\{([^}]+)\}", t)
    if any(e.strip() in MATH_ENVS for e in envs):
        return "\\[" + t + "\\]"

    # --- 3. Старый приём: {\Huge ...} ---
    m = re.match(r"^\{\\(Huge|LARGE|Large|large|huge)\s*(.*)\}$", t)
    if m:
        return "{\\" + m.group(1) + " $" + m.group(2) + "$}"

    # --- 4. Явные текстовые команды ---
    if any(h in t for h in TEXT_HINTS):
        return tex

    # --- 5. Явная выключная математика ---
    if re.search(r"\\\[|\\\]", t):
        return tex

    # --- 5b. Слова вне $...$ при наличии явной математики => текст ---
    if "$" in tex:
        outside = re.sub(r"\$[^$]*\$", " ", tex)
        if (re.search(r"[A-Za-z]{2,}", outside)
                and not re.search(r"\\[A-Za-z]", outside)):
            return tex

    # --- 6. Латинские слова => текст ---
    if _looks_like_words(t):
        return tex

    if not t.strip():
        return t
    return "$" + t + "$"


def _looks_like_words(s: str) -> bool:
    """Похоже ли содержимое на текст с обычными словами (а не на формулу)."""
    # Убираем LaTeX-команды диакритики: na\\"ive, caf\\'e, \\c{c} и т.п.
    accent = re.compile(
        r"""\\(?:['`"^~=.]|[uvHckrbdt](?![A-Za-z]))\s*(?:\{[A-Za-z]\}|[A-Za-z])"""
    )
    stripped = accent.sub("x", s)

    # Оставшаяся команда (\\frac, \\text, \\sum, ...) — почти наверняка формула.
    if "\\" in stripped:
        return False

    words = re.findall(r"[A-Za-z]{2,}", stripped)
    math_marks = len(re.findall(r"[\^_{}=+*/<>|]", stripped))
    has_space = bool(re.search(r"\s", stripped.strip()))

    # Одна буква, записанная командой диакритики: \'e, \"u, \c{c}.
    if not words:
        return (stripped != s and "\\" not in stripped
                and math_marks == 0)

    # Чистые слова без математических знаков — текст.
    if math_marks == 0:
        return True
    # Фраза из нескольких слов с небольшим числом знаков — тоже текст.
    return len(words) >= 2 and has_space and math_marks <= 2


def is_spacer(tex: str) -> bool:
    """Пустая строка или команда-отбивка (\\vspace, \\hfill, ...)."""
    tex = tex.strip()
    if not tex:
        return True
    return bool(re.match(
        r"\\(vspace|hspace|vskip|hskip|smallskip|medskip|bigskip"
        r"|hfill|vfill|newpage|clearpage|par)\b", tex))


def spacer_height(tex: str) -> float:
    """Высота отбивки в единицах Manim."""
    m = re.search(r"\\vspace\*?\{\s*([0-9.]+)\s*(cm|mm|in|pt|em|ex)\s*\}", tex)
    if m:
        v = float(m.group(1))
        u = m.group(2)
        f = {"cm": 1.0, "mm": 0.1, "in": 2.54,
             "pt": 0.0353, "em": 1.0, "ex": 0.5}[u]
        return max(0.05, v * f)
    return 0.45


def strip_trailing_linebreak(s: str) -> str:
    """Убрать один завершающий ``\\\\`` (оформление сценария в TeX-виде)."""
    s = s.rstrip()
    if s.endswith("\\\\"):
        s = s[:-2].rstrip()
    return s


def slide_names(scenes, title_info) -> list:
    """Имена слайдов: Title (если есть), затем Slide01, Slide02, ..."""
    names = [f"Slide{i:02d}" for i in range(1, len(scenes) + 1)]
    if has_title(title_info):
        names.insert(0, "Title")
    return names


def slide_label(index: int, scenes, title_info) -> str:
    """Подпись слайда для терминала: ``Slide04 (Название)``.

    ``index`` — 0 для титульного, 1..N для сцен.
    """
    if index == 0:
        t = (title_info or {}).get("title", "").strip()
        t = " ".join(t.split())
        if len(t) > 60:
            t = t[:57].rstrip() + "…"
        return f"Title ({t})" if t else "Title"
    scene = scenes[index - 1]
    title = " ".join((scene.get("title") or "").split())
    if len(title) > 60:
        title = title[:57].rstrip() + "…"
    return f"Slide{index:02d} ({title})" if title else f"Slide{index:02d}"


# ─────────────────────────────────────────────────────────────────────────────
# 3. ОШИБКИ
# ─────────────────────────────────────────────────────────────────────────────
class ScenarioError(Exception):
    def __init__(self, msg, lineno=None):
        self.msg = msg
        self.lineno = lineno
        super().__init__(msg)

    def __str__(self):
        if self.lineno:
            return f"строка {self.lineno}: {self.msg}"
        return self.msg


# ─────────────────────────────────────────────────────────────────────────────
# 4. ЧТЕНИЕ СЦЕНАРИЯ (txt / docx / doc / md / tex)
# ─────────────────────────────────────────────────────────────────────────────
def find_scenario() -> Path:
    if not HERE.exists():
        raise ScenarioError("папка со скриптом не найдена")
    candidates = []
    for p in HERE.iterdir():
        if not p.is_file():
            continue
        if p.suffix.lower() not in SCENARIO_EXTS:
            continue
        if p.name.lower() == "readme.md":
            continue
        candidates.append(p)
    if not candidates:
        exts = ", ".join(SCENARIO_EXTS)
        raise ScenarioError(
            f"в папке нет файла сценария ({exts}).\n"
            "Положите рядом с build.py файл сценария, например scenario.txt"
        )
    # предпочитаем файл с именем scenario.*
    for p in candidates:
        if p.stem.lower() == "scenario":
            return p
    return sorted(candidates, key=lambda x: x.name.lower())[0]


def _decode(b: bytes) -> str:
    if not b:
        return ""
    for enc in ("utf-8", "cp1251"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(str(path)) as z:
            xml = z.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ScenarioError(f"не удалось прочитать .docx: {e}")
    root = ET.fromstring(xml)
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paras = []
    for p in root.iter(ns + "p"):
        texts = [t.text or "" for t in p.iter(ns + "t")]
        paras.append("".join(texts))
    return "\n".join(paras)


def _doc_text(path: Path) -> str:
    # старый бинарный .doc — пробуем внешние конвертеры
    for cmd in (["antiword", str(path)], ["catdoc", str(path)]):
        try:
            r = subprocess.run(cmd, capture_output=True)
        except FileNotFoundError:
            continue
        if r.returncode == 0 and r.stdout.strip():
            return _decode(r.stdout)

    try:
        outdir = tempfile.mkdtemp(prefix="notae_")
        subprocess.run(
            ["libreoffice", "--headless", "--convert-to",
             "txt:Text (encoded):UTF8", "--outdir", outdir, str(path)],
            capture_output=True, text=True,
        )
        txt = Path(outdir) / (path.stem + ".txt")
        if txt.exists():
            return txt.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        pass

    raise ScenarioError(
        "не удалось прочитать старый .doc.\n"
        "Сохраните файл как .docx или .txt (или установите antiword/catdoc/libreoffice)."
    )


def read_scenario_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".docx":
        return _docx_text(path)
    if ext == ".doc":
        return _doc_text(path)
    return _read_text(path)


def detect_packages(text: str):
    """Пакеты из \\usepackage{...} по всему файлу (кроме комментариев)."""
    found = []
    for m in re.finditer(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}", text):
        if _in_comment(text, m.start()):
            continue
        for p in m.group(1).split(","):
            p = p.strip()
            if p and re.match(r"^[\w.-]+$", p):
                found.append(p)
    return found


# ─────────────────────────────────────────────────────────────────────────────
# 5. ПАРСЕР СЦЕНАРИЯ
# ─────────────────────────────────────────────────────────────────────────────
# Служебные слова: с них начинается новая конструкция.
# ВАЖНО: внутри {...} нельзя начинать строку с этих слов — она оборвёт содержимое.
_SERVICE_RE = re.compile(
    r"(?i)^\s*(?:"
    r"scene\s*:|"
    r"line\s+[^\n:]+:|"
    r"sub\s+[^\n:]+:|"
    r"pause\s*:|"
    r"T\s*:|"
    r"title\s*:|"
    r"author\s*:|affiliation\s*:|event\s*:|date\s*:|"
    r"packages?\s*:|"
    r"style\s+[^\n:]+:|"
    r"common\s*:"
    r")"
)


def _strip_trailing_brace(s: str) -> str:
    """Отбросить одну закрывающую } в конце (если она не экранирована)."""
    s = s.rstrip()
    if not s.endswith("}"):
        return s
    i = len(s) - 2
    n = 0
    while i >= 0 and s[i] == "\\":
        n += 1
        i -= 1
    if n % 2 == 0:          # чётное число '\' => скобка не экранирована
        s = s[:-1]
    return s.rstrip()


def _clean_content(s: str) -> str:
    """Убрать строки-комментарии (%), закрывающую } и ``\\\\``-оформление."""
    s = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("%"))
    s = strip_trailing_linebreak(s)
    s = _strip_trailing_brace(s)
    return strip_trailing_linebreak(s)


def _ends_with_closing_brace(s: str) -> bool:
    """Заканчивается ли содержимое настоящей (неэкранированной) ``}``.

    Игнорируются завершающие пробелы, пустые строки, строки-комментарии и
    необязательный ``\\\\`` после закрывающей скобки. Именно эта проверка
    решает, оборвёт ли служебное слово содержимое ``{...}``.
    """
    lines = s.splitlines()
    while lines and (not lines[-1].strip()
                     or lines[-1].lstrip().startswith("%")):
        lines.pop()
    if not lines:
        return False
    s = "\n".join(lines).rstrip()
    s = strip_trailing_linebreak(s)
    if not s.endswith("}"):
        return False
    # Считаем обратные слэши перед последней скобкой: \} — экранированная.
    i = len(s) - 2
    n = 0
    while i >= 0 and s[i] == "\\":
        n += 1
        i -= 1
    return n % 2 == 0


def _content_after(text: str, pos: int, nl: int, what: str, lineno: int):
    """Содержимое после ключевого слова.

    Начинается с '{' и читается до служебного слова в начале НОВОЙ строки.
    Сбалансированность фигурных скобок не требуется: внутри {...} их может быть
    сколько угодно.

    Служебное слово обрывает содержимое только тогда, когда перед ним уже
    стоит закрывающая ``}`` (пробелы, пустые строки и необязательный ``\\\\``
    после неё не учитываются). Поэтому служебные слова можно писать внутри
    незакрытого ``{...}`` как обычный текст. Закрывающая ``}`` в конце
    отбрасывается.
    """
    seg = text[pos:nl]
    ib = seg.find("{")
    iq = seg.find('"')
    if ib == -1 and iq == -1:
        raise ScenarioError(f"ожидалось {{...}} или \"...\" в «{what}»", lineno)

    # --- содержимое в {...}: до служебного слова на новой строке ---
    if ib != -1 and (iq == -1 or ib < iq):
        start = pos + ib + 1
        cur_nl = text.find("\n", start)
        if cur_nl == -1:                      # последняя строка файла
            return _clean_content(text[start:]), len(text)
        line_start = cur_nl + 1
        skipped = []
        while line_start < len(text):
            line_end = text.find("\n", line_start)
            if line_end == -1:
                line_end = len(text)
            if _SERVICE_RE.match(text[line_start:line_end]):
                if _ends_with_closing_brace(text[start:line_start]):
                    return _clean_content(text[start:line_start]), line_start
                # Похоже на служебное слово, но содержимое ещё не закрыто:
                # считаем строку текстом (и запомним для диагностики).
                skipped.append((
                    text.count("\n", 0, line_start) + 1,
                    text[line_start:line_end].strip()[:40],
                ))
            line_start = line_end + 1
        tail = text[start:]
        if skipped and not _ends_with_closing_brace(tail):
            line_no, word = skipped[0]
            raise ScenarioError(
                f"содержимое «{what}» не закрыто: служебное слово «{word}» "
                f"в строке {line_no} не обрывает его, потому что перед ним "
                f"нет закрывающей `}}`. Поставьте `}}` в конце содержимого "
                f"или перед служебным словом.",
                lineno,
            )
        return _clean_content(tail), len(text)

    # --- старый вариант с кавычками ---
    iq2 = seg.find('"', iq + 1)
    if iq2 == -1:
        raise ScenarioError(f"не закрыта кавычка в «{what}»", lineno)
    return seg[iq + 1:iq2], nl + 1


def _style_into(styles, target: str, rest: str):
    kv = {}
    for item in rest.split():
        if "=" in item:
            k, v = item.split("=", 1)
            kv[k] = v
    if "size" in kv:
        try:
            kv["size"] = float(kv["size"])
        except ValueError:
            raise ScenarioError(f"неверный size={kv['size']!r} в style")
    if "color" in kv:
        kv["color"] = resolve_color(kv["color"])
    low = target.lower()
    if low == "default":
        styles["default"].update(kv)
    elif low.startswith("line "):
        styles["lines"].setdefault(target[5:].strip(), {}).update(kv)
    elif low.startswith("sub "):
        styles["subs"].setdefault(target[4:].strip(), {}).update(kv)


def _apply_style(cur, target: str, rest: str):
    _style_into(cur["styles"], target, rest)


def _parse_t_action(text, pos, nl, delay, rest, cur, lineno):
    """Разобрать действие после 'T: <задержка>'. Вернуть новый pos."""
    # inline-объявление строки:  T: 0.5 line l1: {...}
    m = re.match(r"(?i)^line\s+(\S+?)\s*:", rest)
    if m:
        name = m.group(1)
        content, end = _content_after(text, pos, nl, f"line {name}", lineno)
        cur["lines"][name] = content
        cur["timeline"].append((delay, "add", name))
        return end

    # inline-объявление субтитра:  T: 0.5 sub s1: {...}
    m = re.match(r"(?i)^sub\s+(\S+?)\s*:", rest)
    if m:
        name = m.group(1)
        content, end = _content_after(text, pos, nl, f"sub {name}", lineno)
        cur["subs"][name] = content
        cur["timeline"].append((delay, "sub", name))
        return end

    # удаление
    if rest.endswith("-"):
        core = rest[:-1].strip()
        if core.lower() in ("sub", "sub:"):
            cur["timeline"].append((delay, "subnull", None))
        else:
            cur["timeline"].append((delay, "remove", core))
        return nl + 1

    # показ по имени (строка или субтитр — определим позже)
    if rest:
        cur["timeline"].append((delay, "show", rest.strip()))
    else:
        cur["timeline"].append((delay, "pause", None))
    return nl + 1


def parse_scenario(text: str):
    scenes = []
    packages = []

    # поля титульного слайда
    title = {"title": "", "author": "", "affiliation": "", "event": "", "date": ""}
    title_pause = 4.0

    # общий блок (объявления до первой сцены)
    common_lines = {}
    common_subs = {}
    common_styles = {"default": {}, "lines": {}, "subs": {}}

    cur = None
    pos = 0
    n = len(text)

    while pos < n:
        nl = text.find("\n", pos)
        if nl == -1:
            nl = n
        raw = text[pos:nl]
        # ``\\`` в конце служебной строки — только оформление TeX-исходника.
        s = strip_trailing_linebreak(raw.strip())
        lineno = text.count("\n", 0, pos) + 1

        if not s:
            pos = nl + 1
            continue

        # --- поля титульного слайда ---
        m = re.match(r"(?i)^(title|author|affiliation|event|date)\s*:", s)
        if m:
            key = m.group(1).lower()
            content, end = _content_after(text, pos, nl, key, lineno)
            title[key] = content.strip()
            pos = end
            continue

        # --- маркер общего блока (необязательный) ---
        if re.match(r"(?i)^common\s*:", s):
            pos = nl + 1
            continue

        # --- scene: {...} ---
        if re.match(r"(?i)^scene\s*:", s):
            sc_title, end = _content_after(text, pos, nl, "scene", lineno)
            cur = {
                "title": sc_title.strip(),
                "lines": {}, "subs": {},
                "styles": {"default": {}, "lines": {}, "subs": {}},
                "timeline": [],
                "lineno": lineno,
            }
            scenes.append(cur)
            pos = end
            continue

        # --- line <имя>: {...} ---
        m = re.match(r"(?i)^line\s+(\S+?)\s*:", s)
        if m:
            name = m.group(1)
            content, end = _content_after(text, pos, nl, f"line {name}", lineno)
            if cur is None:
                common_lines[name] = content      # общая строка
            else:
                cur["lines"][name] = content
            pos = end
            continue

        # --- sub <имя>: {...} ---
        m = re.match(r"(?i)^sub\s+(\S+?)\s*:", s)
        if m:
            name = m.group(1)
            content, end = _content_after(text, pos, nl, f"sub {name}", lineno)
            if cur is None:
                common_subs[name] = content       # общий субтитр
            else:
                cur["subs"][name] = content
            pos = end
            continue

        # --- style ... ---
        m = re.match(r"(?i)^style\s+(default|line\s+\S+|sub\s+\S+)\s*:\s*(.*)$", s)
        if m:
            target = m.group(1).strip()
            rest = m.group(2).strip()
            if cur is None:
                _style_into(common_styles, target, rest)
            else:
                _apply_style(cur, target, rest)
            pos = nl + 1
            continue

        # --- package(s): {...} ---
        m = re.match(r"(?i)^packages?\s*:", s)
        if m:
            content, end = _content_after(text, pos, nl, "package", lineno)
            for p in re.split(r"[,\s]+", content):
                p = p.strip()
                if p and re.match(r"^[\w.-]+$", p):
                    packages.append(p)
            pos = end
            continue

        # --- pause: 0.5 ---
        m = re.match(r"(?i)^pause\s*:\s*([0-9]+(?:\.[0-9]+)?)", s)
        if m:
            val = float(m.group(1))
            if cur is None:
                title_pause = val               # выдержка титульного слайда
            else:
                cur["timeline"].append((val, "pause", None))
            pos = nl + 1
            continue

        # --- T: <задержка> <действие> ---
        m = re.match(r"(?i)^T\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(.*)$", s)
        if m:
            if cur is None:
                raise ScenarioError("действие T: до первой сцены (scene:)", lineno)
            delay = float(m.group(1))
            rest = m.group(2).strip()
            pos = _parse_t_action(text, pos, nl, delay, rest, cur, lineno)
            continue

        # всё остальное — мусор/доп. содержание: пропускаем
        pos = nl + 1

    if not scenes:
        raise ScenarioError("в файле не найдено ни одной сцены вида scene: {...}")

    # --- общие строки/субтитры/стили добавляем в каждую сцену ---
    for sc in scenes:
        sc["lines"] = {**common_lines, **sc["lines"]}
        sc["subs"] = {**common_subs, **sc["subs"]}
        sc["styles"] = {
            k: {**common_styles[k], **sc["styles"][k]}
            for k in ("default", "lines", "subs")
        }

    # --- проверки и разрешение имён ---
    for si, sc in enumerate(scenes, 1):
        for idx, (d, kind, name) in enumerate(sc["timeline"]):
            if kind == "show":
                if name in sc["subs"]:
                    sc["timeline"][idx] = (d, "sub", name)
                elif name in sc["lines"]:
                    sc["timeline"][idx] = (d, "add", name)
                else:
                    raise ScenarioError(
                        f"сцена {si}: неизвестное имя «{name}» в T: (нет такой строки/субтитра)",
                        sc["lineno"],
                    )
            elif kind == "remove" and name not in sc["lines"]:
                raise ScenarioError(
                    f"сцена {si}: удаляется неизвестная строка «{name}»",
                    sc["lineno"],
                )

    title_info = {
        "title": title["title"],
        "author": title["author"],
        "affiliation": title["affiliation"],
        "event": title["event"],
        "date": title["date"],
        "pause": title_pause,
    }
    return scenes, packages, title_info


# ─────────────────────────────────────────────────────────────────────────────
# 6. ИНТЕРПРЕТАТОР СЦЕН
# ─────────────────────────────────────────────────────────────────────────────
SLIDE_CODE = r'''

class Slide(Scene):
    data = {}

    def construct(self):
        d = self.data
        self.camera.background_color = BG

        styles = d.get("styles", {})
        default = styles.get("default", {})
        line_styles = styles.get("lines", {})
        sub_styles = styles.get("subs", {})

        self.lines = d.get("lines", {})
        self.subs = d.get("subs", {})
        self.line_mobs = {}
        self.visible = []
        self.sub_mob = None

        # Заголовок необязателен. Жирный, ярко-жёлтый, без подчёркивания.
        t = d.get("title", "")
        if t.strip():
            sep = " " if t.lstrip().startswith("{") else ""
            title = Tex(r"\textbf{" + sep + t + r"}", tex_template=RU,
                        font_size=TITLE, color=YELLOW)
            title.to_edge(UP, buff=0.6)
            self.play(Write(title), run_time=0.5)
            self.mid_y = (title.get_bottom()[1] + (-3.3)) / 2
        else:
            self.mid_y = -0.3

        for delay, kind, name in d.get("timeline", []):
            if delay > 0:
                self.wait(delay)
            if kind == "sub":
                self._set_sub(name, sub_styles)
            elif kind == "subnull":
                self._set_sub(None, sub_styles)
            elif kind == "add":
                self._add(name, line_styles, default)
            elif kind == "remove":
                self._remove(name, line_styles, default)

    # --- вспомогательные методы ---
    def _style(self, name, line_styles, default):
        s = dict(default)
        s.update(line_styles.get(name, {}))
        return s

    def _prepare(self, tex):
        # Общее правило (то же, что в build.py): текст или формула.
        return prepare_line_tex(tex)

    def _make_line(self, name, s):
        tex = self.lines[name]
        if is_spacer(tex):
            # Пустая строка / \vspace — невидимая отбивка (разрыв между блоками).
            return Rectangle(width=0.01, height=spacer_height(tex),
                             stroke_opacity=0, fill_opacity=0)
        # Длинный текст переносится по полям: слева и справа по 2 см.
        body = strip_trailing_linebreak(self._prepare(tex).rstrip())
        size = float(s.get("size", BODY))
        align = s.get("align", "center")
        width_pt = MAX_LINE_WIDTH_PT_AT_36 * 36.0 / max(size, 1.0)
        align_cmd = {"left": r"\raggedright",
                     "right": r"\raggedleft"}.get(align, r"\centering")
        wrapped = (
            r"\parbox{%.1fpt}{%s\noindent " % (width_pt, align_cmd)
            + body + "\n}"
        )
        try:
            return Tex(wrapped, tex_template=RU,
                       font_size=size, color=s.get("color", TEXT))
        except IndexError:
            # команда без видимых глифов — отбивка
            return Rectangle(width=0.01, height=0.45,
                             stroke_opacity=0, fill_opacity=0)

    def _positions(self, line_styles, default):
        mobs = [self.line_mobs[n] for n in self.visible]
        if not mobs:
            return {}
        g = VGroup(*mobs).arrange(DOWN, buff=0.4)
        g.move_to([0, self.mid_y, 0])
        pos = {}
        half = MAX_LINE_WIDTH_UNITS / 2.0
        for n, m in zip(self.visible, mobs):
            s = self._style(n, line_styles, default)
            align = s.get("align", "center")
            if align == "left":
                x = -half + m.width / 2.0
            elif align == "right":
                x = half - m.width / 2.0
            else:
                x = 0
            pos[n] = [x, m.get_center()[1], 0]
        return pos

    def _add(self, name, line_styles, default):
        if name in self.line_mobs:
            return
        s = self._style(name, line_styles, default)
        mob = self._make_line(name, s)
        self.line_mobs[name] = mob
        self.visible.append(name)
        pos = self._positions(line_styles, default)
        mob.move_to(pos[name])
        moves = [self.line_mobs[n].animate.move_to(pos[n]) for n in self.visible if n != name]
        if is_spacer(self.lines[name]):
            self.add(mob)
            if moves:
                self.play(*moves, run_time=0.3)
            return
        anim = s.get("anim", "write")
        if anim == "fade":
            self.play(*moves, FadeIn(mob), run_time=0.5)
        elif anim == "none":
            self.add(mob)
            if moves:
                self.play(*moves, run_time=0.3)
        else:
            self.play(*moves, Write(mob), run_time=0.8)

    def _remove(self, name, line_styles, default):
        if name not in self.line_mobs:
            return
        mob = self.line_mobs.pop(name)
        self.visible.remove(name)
        pos = self._positions(line_styles, default)
        moves = [self.line_mobs[n].animate.move_to(pos[n]) for n in self.visible]
        self.play(FadeOut(mob), *moves, run_time=0.4)

    def _set_sub(self, name, sub_styles):
        if self.sub_mob is not None:
            self.remove(self.sub_mob)
            self.sub_mob = None
        if name is None:
            return
        content = self.subs.get(name, "")
        if not content.strip():
            return
        s = dict(sub_styles.get("default", {}))    # общий стиль субтитров
        s.update(sub_styles.get(name, {}))         # переопределение для имени
        mob = Tex(content, tex_template=RU,
                  font_size=s.get("size", SUB), color=s.get("color", MUTED))
        mob.to_edge(DOWN, buff=0.5)
        self.add(mob)
        self.sub_mob = mob
'''


TITLE_CODE = r'''

class TitleSlide(Scene):
    data = {}

    def _tt(self, text, size, color, bold=False):
        if bold:
            sep = " " if text.lstrip().startswith("{") else ""
            text = r"\textbf{" + sep + text + r"}"
        return Tex(text, tex_template=RU, font_size=size, color=color)

    def construct(self):
        d = self.data
        self.camera.background_color = BG

        rows = []
        t = d.get("title", "").strip()
        if t:
            rows.append(self._tt(t, 56, YELLOW, bold=True))
            rows.append(Line(LEFT * 3.2, RIGHT * 3.2, color=GOLD, stroke_width=2))

        a = d.get("author", "").strip()
        if a:
            rows.append(self._tt(a, 34, TEXT))

        af = d.get("affiliation", "").strip()
        if af:
            rows.append(self._tt(af, 24, MUTED))

        e = d.get("event", "").strip()
        if e:
            rows.append(self._tt(e, 26, BLUE))

        dt = d.get("date", "").strip()
        if dt:
            rows.append(self._tt(dt, 22, MUTED))

        if not rows:
            self.wait(d.get("pause", 4.0))
            return

        group = VGroup(*rows).arrange(DOWN, buff=0.38)
        group.move_to(ORIGIN)
        group.shift(UP * 0.15)

        for m in rows:
            if isinstance(m, Line):
                self.play(Create(m), run_time=0.4)
            else:
                self.play(Write(m), run_time=0.7)

        self.wait(d.get("pause", 4.0))
'''


_MACRO_CMDS = (
    "\\newcommand", "\\renewcommand", "\\providecommand",
    "\\DeclareMathOperator", "\\newtheorem",
    "\\newenvironment", "\\renewenvironment", "\\let",
)


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _read_group(text: str, i: int, open_ch: str, close_ch: str) -> int:
    """Пропустить сбалансированную группу (учитывая \\, вложенность и %-комментарии)."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ScenarioError("не закрыта группа в макросе")


def _read_macro(text: str, i: int, cmd: str) -> int:
    """Вернуть позицию конца объявления макроса (i — сразу после имени команды)."""
    n = len(text)

    if cmd == "\\let":
        nl = text.find("\n", i)
        return n if nl == -1 else nl

    j = _skip_ws(text, i)
    if j < n and text[j] == "*":
        j = _skip_ws(text, j + 1)

    if cmd in ("\\newcommand", "\\renewcommand", "\\providecommand"):
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        elif j < n and text[j] == "\\":
            j += 1
            while j < n and (text[j].isalpha() or text[j] == "@"):
                j += 1
        j = _skip_ws(text, j)
        if j < n and text[j] == "[":
            j = _read_group(text, j, "[", "]")
            j = _skip_ws(text, j)
            if j < n and text[j] == "[":
                j = _read_group(text, j, "[", "]")
                j = _skip_ws(text, j)
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        return j

    if cmd == "\\DeclareMathOperator":
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        j = _skip_ws(text, j)
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        return j

    if cmd == "\\newtheorem":
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        j = _skip_ws(text, j)
        if j < n and text[j] == "[":
            j = _read_group(text, j, "[", "]")
            j = _skip_ws(text, j)
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        j = _skip_ws(text, j)
        if j < n and text[j] == "[":
            j = _read_group(text, j, "[", "]")
        return j

    if cmd in ("\\newenvironment", "\\renewenvironment"):
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        j = _skip_ws(text, j)
        if j < n and text[j] == "[":
            j = _read_group(text, j, "[", "]")
            j = _skip_ws(text, j)
            if j < n and text[j] == "[":
                j = _read_group(text, j, "[", "]")
                j = _skip_ws(text, j)
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        j = _skip_ws(text, j)
        if j < n and text[j] == "{":
            j = _read_group(text, j, "{", "}")
        return j

    return i


def _preamble_head(text: str) -> str:
    """Текст до первой содержательной строки (title / common / scene / ...)."""
    pos = 0
    n = len(text)
    while pos < n:
        nl = text.find("\n", pos)
        if nl == -1:
            nl = n
        if _SERVICE_RE.match(text[pos:nl]):
            return text[:pos]
        pos = nl + 1
    return text


def _in_comment(text: str, p: int) -> bool:
    """Находится ли позиция p после неэкранированного % в своей строке."""
    line_start = text.rfind("\n", 0, p) + 1
    i = line_start
    while i < p:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "%":
            return True
        i += 1
    return False


def extract_macros(text: str):
    """Пользовательские макросы из преамбулы.

    Поддерживаются \\newcommand, \\renewcommand, \\providecommand,
    \\DeclareMathOperator, \\newtheorem, \\newenvironment, \\renewenvironment, \\let.
    """
    macros = []
    i = 0
    n = len(text)
    while i < n:
        best = None
        for cmd in _MACRO_CMDS:
            p = text.find(cmd, i)
            if p != -1 and (best is None or p < best[0]):
                best = (p, cmd)
        if best is None:
            break

        p, cmd = best
        after = p + len(cmd)
        if _in_comment(text, p):
            i = after
            continue
        if after < n and (text[after].isalpha() or text[after] == "@"):
            i = after
            continue
        try:
            end = _read_macro(text, after, cmd)
        except ScenarioError:
            i = after
            continue
        macros.append(text[p:end].strip())
        i = end

    return macros


def build_preamble(extra_packages, macros=()) -> str:
    seen = set()
    lines = []
    # cmap должен подключаться до fontenc
    if any(p.lower() == "cmap" for p in extra_packages):
        lines.append(r"\usepackage{cmap}")
        seen.add("cmap")

    seen |= {n.lower() for n in BASE_NAMES}
    lines.extend(BASE_PREAMBLE)

    for p in extra_packages:
        if p.lower() in seen:
            continue
        seen.add(p.lower())
        lines.append(r"\usepackage{" + p + "}")

    # Пользовательские макросы идут раньше дефолтных определений теорем.
    lines.extend(macros)

    lines.append(r"\makeatletter")
    for env, title in DEFAULT_THEOREMS:
        lines.append(
            r"\@ifundefined{" + env + "}{\\newtheorem{" + env + "}{" + title + "}}{}"
        )
    lines.append(r"\makeatother")
    lines.append(r"\linespread{1}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 7. ГЕНЕРАЦИЯ МОДУЛЯ
# ─────────────────────────────────────────────────────────────────────────────
def has_title(title_info) -> bool:
    if not title_info:
        return False
    return any(title_info.get(k, "").strip()
               for k in ("title", "author", "affiliation", "event", "date"))


def _func_source(fn) -> str:
    """Исходник функции для встраивания в сгенерированный модуль."""
    return textwrap.dedent(inspect.getsource(fn)).strip()


def generate_module(scenes, preamble: str, title_info=None) -> str:
    helpers = "\n\n".join(_func_source(f) for f in (
        prepare_line_tex, _looks_like_words, is_spacer, spacer_height,
        strip_trailing_linebreak,
    ))
    header = (
        '"""СГЕНЕРИРОВАНО build.py — не редактировать."""\n'
        "import re\n"
        "import unicodedata\n"
        "from manim import *\n\n"
        f'BG = "{BG}"\n'
        f'TEXT = "{TEXT}"\n'
        f'MUTED = "{MUTED}"\n'
        f'YELLOW = "{YELLOW}"\n'
        f'GOLD = "{GOLD}"\n'
        f'BLUE = "{BLUE}"\n'
        f'GREEN = "{GREEN}"\n'
        f'RED = "{RED}"\n'
        f'PURPLE = "{PURPLE}"\n\n'
        f"MATH_ENVS = {MATH_ENVS!r}\n"
        f"TEXT_HINTS = {TEXT_HINTS!r}\n"
        f"MAX_LINE_WIDTH_UNITS = {MAX_LINE_WIDTH_UNITS!r}\n"
        f"MAX_LINE_WIDTH_PT_AT_36 = {MAX_LINE_WIDTH_PT_AT_36!r}\n\n"
        + helpers + "\n\n"
        'RU = TexTemplate(preamble=r"""\n' + preamble + '\n""")\n\n'
        f"TITLE = {TITLE}\n"
        f"BODY = {BODY}\n"
        f"SUB = {SUB}\n"
    )
    parts = [header, SLIDE_CODE.strip(), ""]
    if has_title(title_info):
        parts.append(TITLE_CODE.strip())
        parts.append(f"class Title(TitleSlide):\n    data = {title_info!r}\n")
    for i, s in enumerate(scenes, 1):
        parts.append(f"class Slide{i:02d}(Slide):\n    data = {s!r}\n")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 8a. PDF-ВЕРСИЯ (раскадровка состояний; субтитры не включаются)
# ─────────────────────────────────────────────────────────────────────────────
def _pdf_prepare(tex: str) -> str:
    """Те же правила, что и в Slide._prepare: формула или текст."""
    return prepare_line_tex(tex)


def _scene_pages(sc):
    """Состояния слайда: (титул без строк, если он есть) + после каждого add/remove."""
    pages = []
    visible = []
    if sc.get("title", "").strip():
        pages.append([])          # начальное состояние: только заголовок
    for _delay, kind, name in sc.get("timeline", []):
        if kind == "add":
            if name not in visible:
                visible.append(name)
                pages.append(list(visible))
        elif kind == "remove":
            if name in visible:
                visible.remove(name)
                pages.append(list(visible))
        # sub / subnull / pause не меняют набор строк
    return pages


def _pdf_rule(width: str = "5cm", thick: str = "1.2pt") -> str:
    return r"{\color{notaeGOLD}\rule{" + width + "}{" + thick + "}}"


def _pdf_page(title: str, visible, lines) -> str:
    # Заголовок — сверху (как в видео), строки — по центру оставшейся области.
    out = []
    if title.strip():
        out.append(r"\begin{center}")
        out.append(r"{\color{notaeYELLOW}\bfseries\fontsize{44}{52}\selectfont "
                   + title + r"}")
        out.append(r"\end{center}")
    out.append(r"\vspace*{\fill}")
    out.append(r"\begin{center}")
    out.append(r"\fontsize{36}{43}\selectfont")
    for name in visible:
        content = lines.get(name, "")
        if is_spacer(content):
            if content.strip():
                out.append(content.strip() + r"\par\vspace{0.4in}")
            else:
                out.append(r"\par\vspace{0.4in}")
            continue
        body = strip_trailing_linebreak(_pdf_prepare(content).rstrip())
        # Те же поля 2 см, что и в видео: перенос по ширине страницы.
        out.append(r"\parbox{\linewidth}{\centering\noindent "
                   + body + "\n" + r"\par}\vspace{0.4in}")
    out.append(r"\end{center}")
    out.append(r"\vspace*{\fill}")
    return "\n".join(out)


def _pdf_title_page(t) -> str:
    out = [r"\vspace*{\fill}", r"\begin{center}"]
    if t.get("title", "").strip():
        out.append(r"{\color{notaeYELLOW}\bfseries\fontsize{56}{64}\selectfont "
                   + t["title"] + r"}\\[0.5em]")
        out.append(_pdf_rule("6.4in", "1.5pt") + r"\\[1.3em]")
    if t.get("author", "").strip():
        out.append(r"{\color{notaeTEXT}\fontsize{34}{40}\selectfont "
                   + t["author"] + r"}\\[0.5em]")
    if t.get("affiliation", "").strip():
        out.append(r"{\color{notaeMUTED}\fontsize{24}{29}\selectfont "
                   + t["affiliation"] + r"}\\[1.1em]")
    if t.get("event", "").strip():
        out.append(r"{\color{notaeBLUE}\fontsize{26}{31}\selectfont "
                   + t["event"] + r"}\\[0.4em]")
    if t.get("date", "").strip():
        out.append(r"{\color{notaeMUTED}\fontsize{22}{27}\selectfont "
                   + t["date"] + r"}")
    out.append(r"\end{center}")
    out.append(r"\vspace*{\fill}")
    return "\n".join(out)


def build_handout_tex(scenes, title_info, packages, macros) -> str:
    # geometry подключаем сами (с полями/ландшафтом), поэтому убираем из extras
    pre = build_preamble(
        [p for p in packages if p.lower() != "geometry"], macros
    )
    head = [
        r"\documentclass[11pt]{article}",
        pre,
        r"\usepackage{geometry}",
        # страница 16:9, как кадр видео; поля те же — по 2 см.
        r"\geometry{paperwidth=36.1cm,paperheight=20.3cm,margin=2cm}",
        r"\pagestyle{empty}",
        r"\definecolor{notaeBG}{HTML}{121417}",
        r"\definecolor{notaeTEXT}{HTML}{E9E6E1}",
        r"\definecolor{notaeMUTED}{HTML}{A7A39C}",
        r"\definecolor{notaeYELLOW}{HTML}{FFD166}",
        r"\definecolor{notaeGOLD}{HTML}{E3B56B}",
        r"\definecolor{notaeBLUE}{HTML}{7FB3D5}",
        # размеры математики под размеры текста (иначе формулы мельче)
        r"\DeclareMathSizes{36}{36}{25}{18}",
        r"\DeclareMathSizes{44}{44}{31}{22}",
        r"\DeclareMathSizes{56}{56}{39}{28}",
        r"\pagecolor{notaeBG}",
        r"\color{notaeTEXT}",
        r"\begin{document}",
    ]
    body = []
    if has_title(title_info):
        body.append(_pdf_title_page(title_info))
        body.append(r"\newpage")
    for sc in scenes:
        for visible in _scene_pages(sc):
            body.append(_pdf_page(sc.get("title", ""), visible, sc.get("lines", {})))
            body.append(r"\newpage")
    return "\n\n".join(head + body + [r"\end{document}"]) + "\n"


def find_local_latex():
    for cmd in ("pdflatex", "xelatex", "lualatex"):
        if shutil.which(cmd):
            return cmd
    return None


def compile_local(tex_path: Path, engine: str):
    out = tex_path.parent
    cmd = [engine, "-interaction=nonstopmode", "-halt-on-error",
           "-output-directory", str(out), str(tex_path)]
    r = subprocess.run(cmd, cwd=out, capture_output=True)
    log = _decode((r.stdout or b"") + (r.stderr or b""))
    pdf = tex_path.with_suffix(".pdf")
    if r.returncode != 0 or not pdf.exists():
        return False, log[-2500:]
    for ext in (".aux", ".log", ".out", ".toc"):
        try:
            tex_path.with_suffix(ext).unlink()
        except OSError:
            pass
    return True, ""


def compile_online(tex_path: Path, pdf_path: Path):
    import urllib.parse
    import urllib.request

    text = tex_path.read_text(encoding="utf-8")
    url = "https://latexonline.cc/compile?" + urllib.parse.urlencode(
        {"text": text, "command": "pdflatex"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Notae/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
    except Exception as e:          # сеть/сервис недоступны
        return False, f"онлайн-компиляция не удалась: {e}"
    if not data.startswith(b"%PDF"):
        return False, "сервер вернул не PDF"
    pdf_path.write_bytes(data)
    return True, ""


def _input_prompt(prompt: str) -> str:
    # Перевод строки после приглашения делает ввод предсказуемым и в
    # терминале, и при перенаправлении stdin/stdout в файл.
    print(prompt, flush=True)
    return input()


def ask_output():
    """Выбор: видео / PDF / интерактив. Возвращает (видео, pdf, интерактив)."""
    print("Что сгенерировать?")
    print("  1 — видео (MP4)")
    print("  2 — PDF (раскадровка)")
    print("  3 — интерактивная презентация (пока в разработке)")
    print("Видео и PDF можно совместить: введите 1,2.")
    try:
        ans = _input_prompt("Выбор (1/2/3) [1]: ").strip()
    except (EOFError, OSError):
        return True, False, False       # автоматический запуск: только видео
    if not ans:
        return True, False, False
    choices = set(re.findall(r"[123]", ans))
    if not choices:
        print("Не понял выбор — собираю видео.")
        return True, False, False
    if "3" in choices:
        if len(choices) > 1:
            print("Интерактивный режим пока нельзя совмещать с видео/PDF.")
        return False, False, True
    return "1" in choices, "2" in choices, False


def _pdf_worker(result, fn, *args):
    result["ok"], result["msg"] = fn(*args)


# ─────────────────────────────────────────────────────────────────────────────
# 7b. ПРОВЕРКА СЦЕНАРИЯ ДО СБОРКИ (LaTeX, переносы, плотность)
# ─────────────────────────────────────────────────────────────────────────────
def _units_per_pt(size: float) -> float:
    """Сколько единиц Manim занимает 1 pt TeX при данном font_size."""
    return TEX_UNITS_PER_PT_AT_48 * float(size) / 48.0


def _parbox_width_pt(size: float) -> float:
    r"""Ширина \parbox в pt для полей 2 см при данном размере шрифта."""
    return MAX_LINE_WIDTH_PT_AT_36 * 36.0 / max(float(size), 1.0)


def _effective_style(scene, kind: str, name: str) -> dict:
    styles = scene.get("styles", {})
    if kind == "sub":
        base = dict(styles.get("subs", {}).get("default", {}))
        base.update(styles.get("subs", {}).get(name, {}))
    else:
        base = dict(styles.get("default", {}))
        base.update(styles.get("lines", {}).get(name, {}))
    return base


def _static_latex_problem(content: str):
    """Простые ошибки, на которых LaTeX обычно останавливается."""
    # Убираем комментарии, чтобы скобки в них не мешали.
    txt = re.sub(r"(?<!\\)%[^\n]*", "", content)

    i = 0
    depth = 0
    while i < len(txt):
        ch = txt[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return "лишняя закрывающая фигурная скобка"
        i += 1
    if depth:
        return "не закрыта фигурная скобка"

    stack = []
    for m in re.finditer(r"\\(begin|end)\s*\{([^}]*)\}", txt):
        what, env = m.group(1), m.group(2).strip()
        if what == "begin":
            stack.append(env)
        else:
            if not stack or stack[-1] != env:
                return f"непарное окружение \\end{{{env}}}"
            stack.pop()
    if stack:
        return f"не закрыто окружение \\begin{{{stack[-1]}}}"

    if len(re.findall(r"(?<!\\)\$", txt)) % 2:
        return "непарный символ $"
    return None


def _check_items(scenes, title_info):
    """Собрать всё, что нужно измерить и проверить."""
    items = []
    idx = 0
    if has_title(title_info):
        for key, size in (("title", 56), ("author", 34), ("affiliation", 24),
                          ("event", 26), ("date", 22)):
            value = (title_info.get(key) or "").strip()
            if not value:
                continue
            if key == "title":
                sep = " " if value.lstrip().startswith("{") else ""
                body = r"\textbf{" + sep + value + r"}"
            else:
                body = value
            items.append({"id": idx, "slide": 0, "kind": "title_field",
                          "name": key, "size": float(size), "content": body,
                          "spacer": False, "used": True})
            idx += 1

    for si, sc in enumerate(scenes, 1):
        timeline = sc.get("timeline", [])
        used_lines = {n for _, kind, n in timeline if kind == "add"}
        used_subs = {n for _, kind, n in timeline if kind == "sub"}

        title = (sc.get("title") or "").strip()
        if title:
            sep = " " if title.lstrip().startswith("{") else ""
            items.append({"id": idx, "slide": si, "kind": "scene_title",
                          "name": "title", "size": float(TITLE),
                          "content": r"\textbf{" + sep + title + r"}",
                          "spacer": False, "used": True})
            idx += 1

        for name, content in sc.get("lines", {}).items():
            style = _effective_style(sc, "line", name)
            size = float(style.get("size", BODY))
            spacer = is_spacer(content)
            prepared = content
            if not spacer:
                prepared = strip_trailing_linebreak(
                    prepare_line_tex(content).rstrip()
                )
            items.append({"id": idx, "slide": si, "kind": "line",
                          "name": name, "size": size, "content": prepared,
                          "spacer": spacer, "used": name in used_lines})
            idx += 1

        for name, content in sc.get("subs", {}).items():
            style = _effective_style(sc, "sub", name)
            size = float(style.get("size", SUB))
            items.append({"id": idx, "slide": si, "kind": "sub",
                          "name": name, "size": size, "content": content,
                          "spacer": False, "used": name in used_subs})
            idx += 1
    return items


def _probe_document(preamble: str, items):
    """Один TeX-документ, который измеряет все элементы и пишет метрики."""
    lines = [
        r"\documentclass[10pt]{article}",
        preamble,
        r"\newsavebox{\notaebox}",
        r"\begin{document}",
    ]
    for it in items:
        content = it.get("content", "")
        if it.get("spacer"):
            continue
        hsize = _parbox_width_pt(it["size"])
        inherit_hsize = False
        if it["kind"] in ("title_field", "scene_title"):
            # Заголовки не переносим: нужна их настоящая высота.
            hsize = 10000.0
        elif it["kind"] == "sub":
            # Субтитры набираются в стандартной ширине Manim; она зависит от
            # пакета geometry в преамбуле, поэтому берём текущий \hsize.
            inherit_hsize = True

        lines.append(r"\typeout{NOTAE-B:%d}" % it["id"])
        lines.append(r"\begingroup")
        lines.append(r"\typeout{NOTAE-P:%d:N}" % it["id"])
        lines.append(r"\setbox\notaebox=\vbox{\hsize=10000pt "
                     r"\linewidth=10000pt \noindent")
        lines.append(content)
        lines.append(r"\par}")
        lines.append(r"\typeout{NOTAE-N:%d:\the\ht\notaebox:"
                     r"\the\dp\notaebox:\the\baselineskip}" % it["id"])
        lines.append(r"\typeout{NOTAE-P:%d:W}" % it["id"])
        if inherit_hsize:
            lines.append(r"\setbox\notaebox=\vbox{\linewidth=\hsize "
                         r"\noindent")
        else:
            lines.append(r"\setbox\notaebox=\vbox{\hsize=%.2fpt "
                         r"\linewidth=%.2fpt \noindent" % (hsize, hsize))
        lines.append(content)
        lines.append(r"\par}")
        lines.append(r"\typeout{NOTAE-W:%d:\the\ht\notaebox:"
                     r"\the\dp\notaebox:\the\baselineskip}" % it["id"])
        lines.append(r"\endgroup")
    lines.append(r"\end{document}")
    return "\n".join(lines)


def _parse_probe_output(out: str, items):
    """Разобрать лог пробной компиляции: метрики, ошибки, overfull."""
    metrics = {}
    errors = {}
    overfull = {}
    current = None
    phase = ""
    last_error = None
    global_errors = []

    dim_re = re.compile(r"NOTAE-([NW]):(\d+):([0-9.]+)pt:([0-9.]+)pt"
                        r"(?::([0-9.]+)pt)?")
    for raw_line in out.splitlines():
        line = raw_line.strip()
        m = re.match(r"NOTAE-B:(\d+)", line)
        if m:
            current = int(m.group(1))
            last_error = None
            continue
        m = re.match(r"NOTAE-P:(\d+):([NW])", line)
        if m:
            phase = m.group(2)
            continue
        m = dim_re.search(line)
        if m:
            which, iid, h, d, bs = m.groups()
            iid = int(iid)
            key = "nat" if which == "N" else "wrap"
            metrics.setdefault(iid, {})[key] = (
                float(h), float(d), float(bs or 12.0)
            )
            continue
        if line.startswith("Overfull \\hbox"):
            m = re.search(r"\(([0-9.]+)pt too wide\)", line)
            if m and current is not None and phase == "W":
                overfull[current] = max(overfull.get(current, 0.0),
                                        float(m.group(1)))
            continue
        if line.startswith("!"):
            msg = line[1:].strip()
            if current is None:
                if msg not in global_errors:
                    global_errors.append(msg)
                last_error = None
            else:
                errors.setdefault(current, [])
                seen = [e.split(" (l.")[0] for e in errors[current]]
                if msg not in seen:
                    errors[current].append(msg)
                    last_error = msg
                else:
                    # Та же ошибка во втором (измерительном) проходе.
                    last_error = None
            continue
        if line.startswith("l.") and last_error and current is not None:
            # Уточняем последнюю ошибку номером строки пробного файла.
            lst = errors.setdefault(current, [])
            if lst and not lst[-1].endswith(")"):
                lst[-1] = lst[-1] + " (" + line[:80] + ")"
            last_error = None
            continue
        if "Missing character: There is no" in line:
            if current is not None:
                errors.setdefault(current, [])
                msg = "символ не найден в шрифте: " + line.split("no", 1)[-1].strip()
                if msg not in errors[current]:
                    errors[current].append(msg)
            else:
                global_errors.append(line.strip())
    return metrics, errors, overfull, global_errors


def _find_probe_latex():
    for cmd in ("latex", "pdflatex"):
        if shutil.which(cmd):
            return cmd
    return None


def _run_probe(preamble: str, items):
    """Скомпилировать пробный документ. Вернуть (metrics, errors, overfull,
    global_errors, note)."""
    engine = _find_probe_latex()
    if not engine:
        return ({}, {}, {}, [], "LaTeX не найден — проверка LaTeX пропущена")

    # Сначала отсеиваем заведомо битые элементы, чтобы их ошибки не «съели»
    # остальной пробный документ.
    static = {}
    for it in items:
        if it.get("spacer"):
            continue
        problem = _static_latex_problem(it.get("content", ""))
        if problem:
            static[it["id"]] = problem
    probe_items = [it for it in items if it["id"] not in static]

    tmp = Path(tempfile.mkdtemp(prefix="notae_check_"))
    try:
        tex = tmp / "check.tex"
        tex.write_text(_probe_document(preamble, probe_items), encoding="utf-8")
        try:
            r = subprocess.run(
                [engine, "-interaction=nonstopmode", str(tex)],
                cwd=str(tmp), capture_output=True, timeout=180,
            )
            out = _decode((r.stdout or b"") + (r.stderr or b""))
        except subprocess.TimeoutExpired:
            out = ""
            static[-1] = "проверка LaTeX не завершилась за 3 минуты"
        except OSError as e:
            out = ""
            static[-1] = f"не удалось запустить LaTeX: {e}"

        if "NOTAE-B:" not in out:
            log = tmp / "check.log"
            if log.exists():
                out = _decode(log.read_bytes())

        metrics, errors, overfull, global_errors = _parse_probe_output(
            out, probe_items
        )
        for iid, problem in static.items():
            if iid == -1:
                global_errors.append(problem)
            else:
                errors.setdefault(iid, []).append(problem)
        # Ошибки в преамбуле: если маркеров нет вовсе, всё относится к ней.
        return metrics, errors, overfull, global_errors, ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _clean_latex_msg(msg: str) -> str:
    """Убрать из сообщения номер строки пробного файла, оставив фрагмент."""
    msg = re.sub(r"\s*\(l\.\d+\s*", " (фрагмент: ", msg)
    if "(фрагмент: " in msg and not msg.endswith(")"):
        msg += ")"
    return msg.strip()


def preflight(scenes, title_info, preamble, for_video=True) -> list:
    """Полный список ошибок и предупреждений: LaTeX, переносы, вертикаль.

    ``for_video=False`` (только PDF) отключает проверки, относящиеся к кадру
    видео: длину субтитров, переносы и переполнение рабочей области.
    """
    items = _check_items(scenes, title_info)
    metrics, errors, overfull, global_errors, note = _run_probe(
        preamble, items
    )
    if note:
        print("  " + note)

    issues = []

    def add(slide, kind, name, text, severity):
        issues.append({"slide": slide, "kind": kind,
                       "name": name or "", "text": text,
                       "severity": severity})

    for msg in global_errors:
        add(-1, "latex", "", "LaTeX: " + _clean_latex_msg(msg), "error")

    by_id = {it["id"]: it for it in items}
    kind_names = {"line": "строка", "sub": "субтитр",
                  "scene_title": "заголовок сцены",
                  "title_field": "титульное поле"}

    # --- ошибки LaTeX по элементам ---
    for iid, msgs in errors.items():
        it = by_id.get(iid)
        if not it:
            continue
        kind = kind_names.get(it["kind"], "элемент")
        used = it.get("used", True)
        for msg in msgs:
            prefix = f"LaTeX, {kind} «{it['name']}»"
            if not used:
                prefix += " (не используется)"
            add(it["slide"], "latex", it["name"],
                f"{prefix}: {_clean_latex_msg(msg)}",
                "error" if used else "warning")

    # --- субтитры: не более 3 строк (только для видео) ---
    for it in (items if for_video else []):
        if it["kind"] != "sub" or it["spacer"] or not it.get("used", True):
            continue
        met = metrics.get(it["id"], {})
        wr = met.get("wrap")
        if not wr:
            continue
        h, d, bs = wr
        nlines = max(1, int(math.ceil((h + d) / max(bs, 1.0))))
        if nlines > 3:
            add(it["slide"], "sub", it["name"],
                f"субтитр «{it['name']}»: {nlines} "
                f"{_plural_ru(nlines, 'строка', 'строки', 'строк')} "
                f"(рекомендуется не более 3)", "warning")

    # --- строки: перенос из-за длины и неразрывное переполнение ---
    for it in (items if for_video else []):
        if it["kind"] != "line" or it["spacer"] or not it.get("used", True):
            continue
        met = metrics.get(it["id"], {})
        nat, wr = met.get("nat"), met.get("wrap")
        if not nat or not wr:
            continue
        nat_h, nat_d, nat_bs = nat
        wr_h, wr_d, wr_bs = wr
        nat_lines = max(1, int(math.ceil((nat_h + nat_d) / max(nat_bs, 1.0))))
        wr_lines = max(1, int(math.ceil((wr_h + wr_d) / max(wr_bs, 1.0))))
        if wr_lines > nat_lines:
            add(it["slide"], "wrap", it["name"],
                f"строка «{it['name']}»: переносится на {wr_lines} "
                f"{_plural_ru(wr_lines, 'строку', 'строки', 'строк')} "
                f"(из-за длины; не рекомендуется)", "warning")
        if overfull.get(it["id"], 0.0) > 1.0:
            add(it["slide"], "width", it["name"],
                f"строка «{it['name']}»: не помещается по ширине "
                f"(даже с переносом)", "warning")

    # --- вертикаль: одновременно видимые строки (только для видео) ---
    for si, sc in (enumerate(scenes, 1) if for_video else []):
        title_item = next(
            (it for it in items
             if it["slide"] == si and it["kind"] == "scene_title"), None
        )
        title_h = 0.0
        if title_item:
            met = metrics.get(title_item["id"], {}).get("nat")
            if met:
                title_h = (met[0] + met[1]) * _units_per_pt(title_item["size"])
            else:
                title_h = 0.6

        top_limit = 3.4 - title_h if title_item else 3.4
        mid_y = ((top_limit + (-3.3)) / 2.0) if title_item else -0.3
        bottom_limit = -3.3
        height_by_line = {}
        for it in items:
            if it["slide"] != si or it["kind"] != "line":
                continue
            if it["spacer"]:
                height_by_line[it["name"]] = spacer_height(it["content"])
                continue
            met = metrics.get(it["id"], {}).get("wrap")
            if met:
                height_by_line[it["name"]] = (
                    (met[0] + met[1]) * _units_per_pt(it["size"])
                )
            else:
                height_by_line[it["name"]] = 0.34 * it["size"] / 36.0

        seen_states = set()
        worst = None
        for visible in _scene_pages(sc):
            key = tuple(visible)
            if key in seen_states:
                continue
            seen_states.add(key)
            if not visible:
                continue
            total = sum(height_by_line.get(n, 0.45) for n in visible)
            total += 0.4 * (len(visible) - 1)
            top = mid_y + total / 2.0
            bottom = mid_y - total / 2.0
            over = max(0.0, top - top_limit, bottom_limit - bottom)
            if over > 0.02 and (worst is None or over > worst[0]):
                worst = (over, visible)
        if worst:
            over, visible = worst
            cm = over * (20.3 / FRAME_HEIGHT_UNITS)
            names = ", ".join(visible)
            add(si, "overflow", "",
                f"одновременно видимые строки не помещаются в рабочую область "
                f"(лишние {cm:.1f} см; состояние: {names})", "warning")

    return issues


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _sort_issues(issues):
    return sorted(
        issues,
        key=lambda x: (
            1 if x["slide"] < 0 else 0,
            x["slide"] if x["slide"] >= 0 else 99,
            ISSUE_ORDER.get(x["kind"], 9),
            x["name"],
        ),
    )


def _split_issues(issues):
    """Разделить замечания на ошибки (срывают сборку) и предупреждения."""
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") != "error"]
    return errors, warnings


def _issue_label(issue, scenes, title_info) -> str:
    if issue["slide"] < 0:
        return "Все слайды (LaTeX-преамбула)"
    return slide_label(issue["slide"], scenes, title_info)


def _unique_issue_labels(issues, scenes, title_info):
    labels = []
    for it in _sort_issues(issues):
        label = _issue_label(it, scenes, title_info)
        if label not in labels:
            labels.append(label)
    return labels


def _issue_counts_text(errors, warnings) -> str:
    parts = []
    if errors:
        parts.append(f"ошибок — {len(errors)}")
    if warnings:
        parts.append(f"предупреждений — {len(warnings)}")
    return ", ".join(parts)


def _print_grouped_issues(issues, scenes, title_info):
    current = object()
    for it in _sort_issues(issues):
        label = _issue_label(it, scenes, title_info)
        if label != current:
            print(f"  {label}")
            current = label
        print(f"      • {it['text']}")


def print_issues(issues, scenes, title_info, header=None):
    """Полный отчёт: сначала ошибки, затем предупреждения.

    Внутри каждого блока порядок — по слайдам, затем по типу.
    """
    errors, warnings = _split_issues(issues)
    if not errors and not warnings:
        return
    if header:
        print()
        print(header)

    if errors:
        print()
        print(f"Ошибки ({len(errors)}) — могут сорвать сборку:")
        _print_grouped_issues(errors, scenes, title_info)
        print()
        print("Слайды с ошибками:")
        for label in _unique_issue_labels(errors, scenes, title_info):
            print("  " + label)

    if warnings:
        print()
        print(f"Предупреждения ({len(warnings)}) — на сборку не влияют:")
        _print_grouped_issues(warnings, scenes, title_info)
        print()
        print("Слайды с предупреждениями:")
        for label in _unique_issue_labels(warnings, scenes, title_info):
            print("  " + label)


def print_error_brief(errors, scenes, title_info, header="Ошибки"):
    """Короткий список ошибок: по одной строке на ошибку."""
    if not errors:
        return
    print()
    print(f"{header} ({len(errors)}):")
    for it in _sort_issues(errors):
        print(f"  {_issue_label(it, scenes, title_info)}: {it['text']}")


def _print_warning_block(warnings, scenes, title_info, header):
    if not warnings:
        return
    kind_short = {
        "wrap": "длинная строка",
        "width": "ширина строки",
        "sub": "длинный субтитр",
        "overflow": "плотность слайда",
        "latex": "LaTeX в неиспользуемой строке",
    }
    by_slide = {}
    for it in _sort_issues(warnings):
        label = _issue_label(it, scenes, title_info)
        by_slide.setdefault(label, [])
        short = kind_short.get(it["kind"], "предупреждение")
        if short not in by_slide[label]:
            by_slide[label].append(short)
    print()
    print(header)
    for label, kinds in by_slide.items():
        print(f"  {label}: {', '.join(kinds)}")


def print_warning_summary(warnings, scenes, title_info):
    """Короткое напоминание о предупреждениях после успешной сборки."""
    _print_warning_block(
        warnings, scenes, title_info,
        f"Предупреждения ({len(warnings)}) — на сборку не влияют, "
        "пересборка не нужна:",
    )


def _load_state():
    """Прочитать и разобрать сценарий. При ошибке вернуть (None, сообщение)."""
    try:
        scenario = find_scenario()
        text = read_scenario_text(scenario)
        scenes, declared_pkgs, title_info = parse_scenario(text)
        packages = detect_packages(text) + declared_pkgs
        macros = extract_macros(_preamble_head(text))
        preamble = build_preamble(packages, macros)
        names = slide_names(scenes, title_info)
        labels = {}
        for n in names:
            if n == "Title":
                labels[n] = slide_label(0, scenes, title_info)
            else:
                # SlideNN -> номер сцены NN (с единицы).
                labels[n] = slide_label(int(n[5:]), scenes, title_info)
        return {
            "scenario": scenario,
            "text": text,
            "scenes": scenes,
            "title_info": title_info,
            "packages": packages,
            "macros": macros,
            "preamble": preamble,
            "names": names,
            "labels": labels,
        }, None
    except ScenarioError as e:
        return None, f"Ошибка сценария: {e}"
    except PermissionError as e:
        return None, f"Нет доступа к файлу: {e}"
    except Exception as e:
        return None, f"Не удалось прочитать сценарий: {e}"


def _wait_enter(prompt: str) -> bool:
    print(prompt, flush=True)
    try:
        input()
        return True
    except (EOFError, OSError):
        print("(ввод недоступен — продолжаем)", flush=True)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# 8. РЕНДЕР, СКЛЕЙКА, УБОРКА
# ─────────────────────────────────────────────────────────────────────────────
def valid_video(p: Path) -> bool:
    if not p.exists() or p.stat().st_size == 0:
        return False
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(p)],
            capture_output=True, text=True, errors="replace",
        )
    except OSError:
        return False
    try:
        return float(r.stdout.strip()) > 0
    except ValueError:
        return False


def render_one(name: str):
    work = WORK_DIR / name
    cmd = [
        "manim", QUALITY, "--fps", str(FPS), "--disable_caching",
        "--media_dir", str(work), GENERATED, name,
    ]
    # UTF-8 в дочернем процессе: Manim печатает содержимое строк в лог, а
    # диакритика (é, ï, ...) не влезает в cp1251 и раньше роняла рендер.
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    try:
        r = subprocess.run(cmd, cwd=HERE, capture_output=True, env=env)
    except OSError as e:
        return name, False, f"не удалось запустить manim: {e}"
    if r.returncode != 0:
        return name, False, _decode((r.stdout or b"") + (r.stderr or b""))

    found = list((work / "videos").rglob(f"{name}.mp4"))
    if not found:
        return name, False, f"после рендера не найден {name}.mp4"
    target = SLIDES_DIR / f"{name}.mp4"
    try:
        target.unlink()
    except OSError:
        pass
    try:
        shutil.move(str(found[0]), str(target))
    except OSError as e:
        return name, False, f"не удалось сохранить {target.name}: {e}"
    if not valid_video(target):
        return name, False, f"{target.name} получился пустым"
    return name, True, ""


def render_parallel(names, labels=None):
    labels = labels or {}
    SLIDES_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    failed = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
        futures = [ex.submit(render_one, n) for n in names]
        for fut in as_completed(futures):
            name, good, err = fut.result()
            label = labels.get(name, name)
            if good:
                print(f"[готово] {label}", flush=True)
            else:
                ok = False
                failed.append(name)
                print(f"[ОШИБКА] {label}", flush=True)
                _print_latex_hint(err, name)
    if failed:
        print("Не удалось собрать: " + ", ".join(
            labels.get(n, n) for n in sorted(failed)
        ))
    return ok, failed


def _print_latex_hint(err: str, name: str = ""):
    """Краткая суть ошибки LaTeX: строка '! ...' и 'l.NN ...'."""
    def clean(t):
        return re.sub(r"[│┃|]", "", t).strip()

    def extract(text):
        m = re.search(r"^!\s[^\n]*", text, re.M)
        if not m:
            m = re.search(r"!\s+(?:LaTeX|Undefined|Missing|Extra|Package|Font)[^\n]*", text)
        first = clean(m.group(0))[:300] if m else ""
        n = re.search(r"^l\.\d+[^\n]*", text, re.M)
        second = clean(n.group(0))[:300] if n else ""
        return first, second

    # 1) настоящий LaTeX-лог (самый свежий, где есть ошибка)
    if name:
        logs = sorted(
            (WORK_DIR / name / "Tex").glob("*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for log in logs:
            first, second = extract(_read_text(log))
            if first:
                print("        " + first, flush=True)
                if second:
                    print("        " + second, flush=True)
                return

    # 2) вывод Manim
    first, second = extract(err)
    if first:
        print("        " + first, flush=True)
        if second:
            print("        " + second, flush=True)
        return

    lines = [clean(l) for l in err.splitlines() if clean(l)]
    for l in lines[-3:]:
        print("        " + l[:200], flush=True)


def concat(names) -> bool:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    lst = WORK_DIR / "concat.txt"
    lines = []
    for n in names:
        p = SLIDES_DIR / f"{n}.mp4"
        if not p.exists():
            return False
        lines.append(f"file '{p.as_posix()}'")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", str(FINAL)],
            capture_output=True,
        )
    except OSError as e:
        print(f"Не удалось запустить ffmpeg: {e}")
        return False
    if r.returncode != 0:
        print("Ошибка ffmpeg при склейке:")
        print(_decode(r.stderr or b"")[-1500:])
        return False
    return valid_video(FINAL)


def remove_stale_slides(names):
    """Удалить из media/slides старые Title/SlideNN, которых уже нет."""
    if not SLIDES_DIR.exists():
        return
    keep = set(names)
    for p in sorted(SLIDES_DIR.glob("*.mp4")):
        if not re.fullmatch(r"(?:Title|Slide\d+)", p.stem):
            continue
        if p.stem in keep:
            continue
        try:
            p.unlink()
            print(f"[устарело] удалён {p.name}", flush=True)
        except OSError:
            pass


def cleanup():
    """Оставить только media/slides/*.mp4 и media/final.mp4, остальное удалить."""
    shutil.rmtree(WORK_DIR, ignore_errors=True)
    for p in (HERE / GENERATED,):
        try:
            p.unlink()
        except OSError:
            pass
    shutil.rmtree(HERE / "__pycache__", ignore_errors=True)
    if MEDIA.exists():
        for child in MEDIA.iterdir():
            if child.name in ("slides", "final.mp4", "handout.tex", "handout.pdf"):
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except OSError:
                    pass


def ask_continue() -> bool:
    try:
        ans = _input_prompt(
            "Использовать готовые видео из media/slides/ "
            "(y — доделать недостающие, n — очистить и собрать заново): "
        ).strip().lower()
        return ans.startswith(("y", "д"))
    except (EOFError, OSError):
        return True


# ─────────────────────────────────────────────────────────────────────────────
# 9. MAIN
# ─────────────────────────────────────────────────────────────────────────────
def _project_name() -> str:
    """Notæ, если консоль умеет её напечатать; иначе Notae."""
    name = "Notæ"
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        name.encode(enc)
        return name
    except (UnicodeEncodeError, LookupError):
        return "Notae"


def print_banner():
    print()
    print("=" * 60)
    print(f"  {_project_name()} — генератор презентаций из сценарного файла")
    print("=" * 60)
    print()


def _pause_exit():
    """Не дать окну закрыться сразу после завершения (двойной клик)."""
    try:
        if sys.stdin and sys.stdin.isatty():
            input("\nНажмите Enter, чтобы закрыть окно...")
    except (EOFError, OSError):
        pass


def _fail(msg: str):
    print(msg)
    _pause_exit()
    sys.exit(1)


def _print_state(state, reloaded=False):
    print("Сценарий: " + state["scenario"].name
          + (" (перечитан)" if reloaded else ""))
    if state["macros"]:
        print(f"Пользовательских макросов: {len(state['macros'])}")
    if has_title(state["title_info"]):
        print("Титульный слайд: Title")
    print("Слайды: " + ", ".join(state["names"]))


def _scene_key(scene) -> str:
    data = {k: v for k, v in scene.items() if k != "lineno"}
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def _state_signature(state):
    return (len(state["scenes"]), has_title(state["title_info"]))


def _changed_slides(old, new) -> list:
    """Какие ролики надо перерендерить после правки сценария."""
    if old["preamble"] != new["preamble"]:
        return list(new["names"])
    changed = []
    if has_title(new["title_info"]):
        if (json.dumps(old["title_info"], sort_keys=True, ensure_ascii=False,
                       default=str)
                != json.dumps(new["title_info"], sort_keys=True,
                              ensure_ascii=False, default=str)):
            changed.append("Title")
    for i, (a, b) in enumerate(zip(old["scenes"], new["scenes"]), 1):
        if _scene_key(a) != _scene_key(b):
            changed.append(f"Slide{i:02d}")
    return changed


def _ask_after_fix(errors, warnings, failed, state, gen_video, gen_pdf,
                   video_ok, pdf_ok) -> bool:
    print()
    if errors:
        print("Нужно исправить ошибки в сценарии.")
    else:
        print("Нужно разобраться с ошибкой сборки.")
    if errors:
        print_error_brief(errors, state["scenes"], state["title_info"])
    if failed:
        print("Не удалось собрать: " + ", ".join(
            state["labels"].get(n, n) for n in sorted(failed)
        ))
    if gen_pdf and not pdf_ok:
        print("PDF собрать не удалось.")
    if gen_video and not video_ok and not failed:
        print("Цельное видео собрать не удалось.")
    _print_warning_block(
        warnings, state["scenes"], state["title_info"],
        f"Предупреждения ({len(warnings)}) — на сборку не влияют:",
    )
    try:
        ans = _input_prompt(
            "Исправить ошибки и продолжить? (y/n): "
        ).strip().lower()
    except (EOFError, OSError):
        return False
    return ans.startswith(("y", "д"))


def _ask_full_rebuild() -> bool:
    try:
        ans = _input_prompt("Пересобрать всё заново? (y/n): ").strip().lower()
    except (EOFError, OSError):
        return False
    return ans.startswith(("y", "д"))


def _load_after_edit():
    """Дождаться Enter, перечитать сценарий; None — если ввода нет."""
    while True:
        ok = _wait_enter(
            "Исправьте сценарий, сохраните файл и нажмите Enter, "
            "чтобы проверить заново..."
        )
        if not ok:
            return None
        new, err = _load_state()
        if new:
            _print_state(new, reloaded=True)
            return new
        print(err)
        print("Сценарий не прочитан. Исправьте его и нажмите Enter ещё раз.")


def _preflight_with_fix(state, gen_video, gen_pdf):
    """Проверить сценарий; при ошибках дать один шанс исправить."""
    issues = preflight(state["scenes"], state["title_info"],
                       state["preamble"], for_video=gen_video)
    errors, warnings = _split_issues(issues)
    if not errors and not warnings:
        print("Проверка сценария: ошибок и предупреждений нет.")
        return state, []

    header = "Проверка сценария: " + _issue_counts_text(errors, warnings) + "."
    print_issues(issues, state["scenes"], state["title_info"], header=header)

    if errors:
        suffix = (" (предупреждения можно оставить)" if warnings else "")
        prompt = (
            f"Исправьте ошибки{suffix}, сохраните файл и нажмите Enter, "
            "чтобы проверить заново (Enter без изменений — начать сборку)."
        )
    else:
        prompt = (
            "Предупреждения не влияют на сборку. Можно оставить всё как есть "
            "и нажать Enter (или исправить и нажать Enter для повторной проверки)."
        )
    ok = _wait_enter(prompt)
    if not ok:
        if errors:
            print("Ошибки остаются — сборка продолжится.")
        else:
            print("Предупреждения остаются — сборка продолжится.")
        return state, issues

    while True:
        new, err = _load_state()
        if new:
            break
        print(err)
        ok = _wait_enter(
            "Сценарий не прочитан. Исправьте его и нажмите Enter ещё раз."
        )
        if not ok:
            return state, issues

    _print_state(new, reloaded=True)
    new_issues = preflight(new["scenes"], new["title_info"],
                           new["preamble"], for_video=gen_video)
    new_errors, new_warnings = _split_issues(new_issues)
    if new_errors:
        extra = (f"; предупреждений: {len(new_warnings)}"
                 if new_warnings else "")
        print()
        print(f"Остались ошибки: {len(new_errors)}{extra}. Сборка начнётся; "
              "подробности — после её завершения.")
        print("Слайды с ошибками: " + ", ".join(
            _unique_issue_labels(new_errors, new["scenes"], new["title_info"])
        ))
        print("Не редактируйте сценарий во время сборки.")
    elif new_warnings:
        print()
        print(f"Остались только предупреждения: {len(new_warnings)}. "
              "На сборку они не влияют; сборка начнётся. "
              "Не редактируйте сценарий во время сборки.")
    else:
        print()
        print("Ошибок и предупреждений не осталось. Сборка начнётся.")
    return new, new_issues


def _start_pdf(state):
    """Запустить сборку PDF в фоне. Вернуть (thread, результат)."""
    result = {"ok": False, "msg": "", "started": False}
    tex = build_handout_tex(state["scenes"], state["title_info"],
                            state["packages"], state["macros"])
    HANDOUT_TEX.parent.mkdir(parents=True, exist_ok=True)
    HANDOUT_TEX.write_text(tex, encoding="utf-8")
    engine = find_local_latex()
    thread = None
    if engine:
        print(f"PDF: локальная компиляция ({engine}), без сети.")
        thread = threading.Thread(
            target=_pdf_worker,
            args=(result, compile_local, HANDOUT_TEX, engine),
            daemon=True,
        )
    else:
        print("Локальный LaTeX не найден.")
        print("Для PDF нужен доступ к сети: текст презентации будет отправлен")
        print("на сторонний сервер latexonline.cc "
              "(конфиденциальность не гарантируется).")
        try:
            ans = _input_prompt(
                "Продолжить онлайн-компиляцию? (y/n): "
            ).strip().lower()
        except (EOFError, OSError):
            ans = "n"
        if ans.startswith(("y", "д")):
            thread = threading.Thread(
                target=_pdf_worker,
                args=(result, compile_online, HANDOUT_TEX, HANDOUT_PDF),
                daemon=True,
            )
        else:
            print(f"PDF не собирался; исходник сохранён: {HANDOUT_TEX}")
    result["started"] = thread is not None
    if thread:
        thread.start()
    return thread, result


def _run_build(state, gen_video, gen_pdf, mode="initial", selected=None,
               ask_continue_flag=True):
    """Один проход сборки. mode: initial / full / incremental."""
    scenes = state["scenes"]
    title_info = state["title_info"]
    names = state["names"]
    labels = state["labels"]
    failed = []
    video_ok = True

    if gen_video:
        (HERE / GENERATED).write_text(
            generate_module(scenes, state["preamble"], title_info),
            encoding="utf-8",
        )

    pdf_thread = pdf_result = None
    if gen_pdf:
        pdf_thread, pdf_result = _start_pdf(state)

    if gen_video:
        SLIDES_DIR.mkdir(parents=True, exist_ok=True)
        if mode == "full":
            shutil.rmtree(SLIDES_DIR, ignore_errors=True)
            SLIDES_DIR.mkdir(parents=True, exist_ok=True)
            existing = []
        else:
            existing = [n for n in names
                        if valid_video(SLIDES_DIR / f"{n}.mp4")]
            if mode == "initial" and existing:
                print(f"Готовых слайдов: {len(existing)} / {len(names)}")
                if ask_continue_flag and not ask_continue():
                    shutil.rmtree(SLIDES_DIR, ignore_errors=True)
                    SLIDES_DIR.mkdir(parents=True, exist_ok=True)
                    existing = []

        if mode == "incremental":
            missing = [n for n in (selected or []) if n in names]
            for n in names:
                if n not in missing and not valid_video(
                        SLIDES_DIR / f"{n}.mp4"):
                    missing.append(n)
            print(f"К досборке: {len(missing)} из {len(names)}")
        else:
            missing = [n for n in names if n not in existing]
            print(f"Всего слайдов: {len(names)}, к рендеру: {len(missing)}")

        if missing:
            video_ok, failed = render_parallel(missing, labels)

        all_ready = all(valid_video(SLIDES_DIR / f"{n}.mp4") for n in names)
        if video_ok and all_ready:
            if concat(names):
                print(f"Цельное видео: {FINAL}")
                remove_stale_slides(names)
            else:
                print("Не удалось собрать цельное видео.")
                video_ok = False
        else:
            print("Не все слайды готовы — цельное видео не собиралось.")
            video_ok = False

    if pdf_thread:
        pdf_thread.join()
        if pdf_result["ok"]:
            print(f"PDF: {HANDOUT_PDF}")
        elif pdf_result.get("started"):
            print("PDF собрать не удалось.")
            if pdf_result["msg"]:
                print(pdf_result["msg"])
        else:
            print(f"PDF не собирался; исходник сохранён: {HANDOUT_TEX}")

    cleanup()
    pdf_ok = True
    if pdf_result and pdf_result.get("started"):
        pdf_ok = pdf_result["ok"]
    return {
        "video_ok": video_ok if gen_video else True,
        "failed": failed,
        "pdf_ok": pdf_ok,
        "pdf_result": pdf_result,
    }


def _print_summary(gen_video, gen_pdf, result, has_errors=False):
    ok = True
    if gen_video and not result["video_ok"]:
        ok = False
    if gen_pdf and not result["pdf_ok"]:
        ok = False
    print()
    print("=" * 60)
    if not ok:
        print("  Сборка завершена с ошибками.")
    elif has_errors:
        print("  Готово, но в сценарии остались ошибки.")
    else:
        print("  Готово!")
    if gen_video:
        print(f"  Слайды: {SLIDES_DIR}")
        if result["video_ok"]:
            print(f"  Видео:  {FINAL}")
    if gen_pdf:
        pdf_result = result.get("pdf_result") or {}
        if pdf_result.get("ok"):
            print(f"  PDF:    {HANDOUT_PDF}")
            print(f"  LaTeX:  {HANDOUT_TEX}")
        else:
            print(f"  LaTeX:  {HANDOUT_TEX} (PDF не собран)")
    print("=" * 60)


def _run_interactive_stub():
    print()
    print("Интерактивная презентация — режим в разработке.")
    print("Планируется показ слайдов в темпе докладчика: управление с клавиатуры,")
    print("переходы между состояниями слайда, заметки, таймер и дополнительные")
    print("инструменты. Пока выберите видео (1) или PDF (2).")


def main():
    print_banner()
    state, err = _load_state()
    if not state:
        _fail(err)
    _print_state(state)

    gen_video, gen_pdf, gen_interactive = ask_output()
    if gen_interactive:
        _run_interactive_stub()
        _pause_exit()
        return
    if not gen_video and not gen_pdf:
        print("Ничего не выбрано.")
        _pause_exit()
        return

    state, issues = _preflight_with_fix(state, gen_video, gen_pdf)

    mode = "initial"
    selected = None
    while True:
        result = _run_build(state, gen_video, gen_pdf, mode, selected)
        errors_now, warnings_now = _split_issues(issues)
        _print_summary(gen_video, gen_pdf, result,
                       has_errors=bool(errors_now))

        failed = result["failed"]
        video_ok = result["video_ok"]
        pdf_ok = result["pdf_ok"]
        hard_failure = bool(
            errors_now or failed
            or (gen_video and not video_ok)
            or (gen_pdf and not pdf_ok)
        )
        if not hard_failure:
            # Только предупреждения: сборка успешна, пересборка не нужна.
            print_warning_summary(warnings_now, state["scenes"],
                                  state["title_info"])
            break

        if not _ask_after_fix(errors_now, warnings_now, failed, state,
                              gen_video, gen_pdf, video_ok, pdf_ok):
            break

        new_state = _load_after_edit()
        if not new_state:
            print("Правки не внесены — выходим.")
            break

        if _state_signature(new_state) != _state_signature(state):
            print()
            if len(new_state["scenes"]) != len(state["scenes"]):
                print("ОШИБКА: количество сцен изменилось "
                      f"(было {len(state['scenes'])}, "
                      f"стало {len(new_state['scenes'])}).")
            else:
                print("ОШИБКА: изменился набор слайдов "
                      "(титульный слайд появился или исчез).")
            print("Инкрементальная сборка невозможна — нужна полная пересборка.")
            if not _ask_full_rebuild():
                break
            state = new_state
            issues = preflight(state["scenes"], state["title_info"],
                               state["preamble"], for_video=gen_video)
            errors_now, warnings_now = _split_issues(issues)
            if errors_now:
                extra = (f", предупреждений — {len(warnings_now)}"
                         if warnings_now else "")
                print(f"Перед пересборкой остались ошибки: "
                      f"{len(errors_now)}{extra} — подробности были выше.")
                print("Не редактируйте сценарий во время сборки.")
            elif warnings_now:
                print(f"Перед пересборкой остались только предупреждения: "
                      f"{len(warnings_now)}; на сборку они не влияют.")
                print("Не редактируйте сценарий во время сборки.")
            mode, selected = "full", None
            continue

        changed = _changed_slides(state, new_state)
        selected = sorted(set(changed) | set(failed))
        # Если ролик потерялся — тоже дособерём.
        if gen_video:
            for n in new_state["names"]:
                if not valid_video(SLIDES_DIR / f"{n}.mp4"):
                    selected.append(n)
            selected = sorted(set(selected))

        if not changed and not failed and not selected:
            print()
            print("Сценарий не изменился — ошибки и предупреждения остались "
                  "без изменений.")
            break

        state = new_state
        issues = preflight(state["scenes"], state["title_info"],
                           state["preamble"], for_video=gen_video)
        errors_now, warnings_now = _split_issues(issues)
        if errors_now:
            extra = (f"; предупреждений: {len(warnings_now)}"
                     if warnings_now else "")
            print()
            print(f"После правки остались ошибки: {len(errors_now)}{extra}. "
                  "Сборка начнётся; подробности — после её завершения.")
            print("Слайды с ошибками: " + ", ".join(
                _unique_issue_labels(errors_now, state["scenes"],
                                     state["title_info"])
            ))
            if not selected:
                print("Изменённых слайдов нет — пересобирать нечего.")
                break
            print("Не редактируйте сценарий во время сборки.")
        elif warnings_now:
            print()
            print(f"После правки остались только предупреждения: "
                  f"{len(warnings_now)}; на сборку они не влияют. "
                  "Не редактируйте сценарий во время сборки.")
        else:
            print()
            print("После правки ошибок и предупреждений нет. "
                  "Сборка начнётся.")

        mode = "incremental"
        # цикл повторится и соберёт только изменённые/неудавшиеся слайды

    if gen_video and not result["video_ok"]:
        _pause_exit()
        sys.exit(1)
    _pause_exit()


if __name__ == "__main__":
    main()
