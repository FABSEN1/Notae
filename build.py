r"""Notae — сборка презентации из файла сценария.

Запуск:  python build.py   (или двойной клик)

Скрипт сам находит файл сценария (txt / doc / docx / md / tex) в своей папке,
рендерит слайды и склеивает их в цельное видео.

Результат:
  media/slides/Slide00.mp4, Slide01.mp4, ...
  media/final.mp4

Полное описание формата сценария и возможностей — в README.md.
"""

import re
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from xml.etree import ElementTree as ET

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
    """Пакеты из \\usepackage{...} по всему файлу."""
    found = []
    for m in re.finditer(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}", text):
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
    """Убрать строки-комментарии (%) и закрывающую } в конце."""
    s = "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("%"))
    return _strip_trailing_brace(s)


def _content_after(text: str, pos: int, nl: int, what: str, lineno: int):
    """Содержимое после ключевого слова.

    Начинается с '{' и читается до служебного слова в начале НОВОЙ строки.
    Сбалансированность фигурных скобок не требуется: внутри {...} их может быть
    сколько угодно. Закрывающая '}' необязательна — одиночная неэкранированная
    '}' в конце отбрасывается.
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
        while line_start < len(text):
            line_end = text.find("\n", line_start)
            if line_end == -1:
                line_end = len(text)
            if _SERVICE_RE.match(text[line_start:line_end]):
                return _clean_content(text[start:line_start]), line_start
            line_start = line_end + 1
        return _clean_content(text[start:]), len(text)

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
        s = raw.strip()
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

    MATH_ENVS = {"aligned", "align", "align*", "gather", "gather*", "split",
                 "matrix", "pmatrix", "bmatrix", "Bmatrix", "vmatrix",
                 "Vmatrix", "cases", "array", "eqnarray", "eqnarray*",
                 "multline", "multline*"}
    TEXT_HINTS = ("\\begin{", "\\vspace", "\\hspace", "\\vskip", "\\hskip",
                  "\\textbf", "\\textit", "\\emph", "\\underline",
                  "\\noindent", "\\centering", "\\par", "\\newline", "\\\\",
                  "\\hfill", "\\vfill", "\\rule", "\\includegraphics",
                  "\\texttt", "\\textsf", "\\textrm", "\\textsc")

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
        # Кириллица => текстовый режим; иначе пытаемся понять, это формула или текст.
        if re.search(r"[А-Яа-яЁё]", tex):
            return tex
        t = tex.replace("$", "")
        envs = re.findall(r"\\begin\{([^}]+)\}", t)
        if any(e.strip() in self.MATH_ENVS for e in envs):
            return "\\[" + t + "\\]"
        m = re.match(r"^\{\\(Huge|LARGE|Large|large|huge)\s*(.*)\}$", t)
        if m:
            return "{\\" + m.group(1) + " $" + m.group(2) + "$}"
        if any(h in t for h in self.TEXT_HINTS):
            return t
        if not t.strip():
            return t
        return "$" + t + "$"

    def _is_spacer(self, name):
        tex = self.lines[name].strip()
        if not tex:
            return True
        return bool(re.match(
            r"\\(vspace|hspace|vskip|hskip|smallskip|medskip|bigskip"
            r"|hfill|vfill|newpage|clearpage|par)\b", tex))

    def _spacer_height(self, tex):
        m = re.search(r"\\vspace\*?\{\s*([0-9.]+)\s*(cm|mm|in|pt|em|ex)\s*\}", tex)
        if m:
            v = float(m.group(1))
            u = m.group(2)
            f = {"cm": 1.0, "mm": 0.1, "in": 2.54,
                 "pt": 0.0353, "em": 1.0, "ex": 0.5}[u]
            return max(0.05, v * f)
        return 0.45

    def _make_line(self, name, s):
        tex = self.lines[name]
        if self._is_spacer(name):
            # Пустая строка / \vspace — невидимая отбивка (разрыв между блоками).
            return Rectangle(width=0.01, height=self._spacer_height(tex),
                             stroke_opacity=0, fill_opacity=0)
        try:
            return Tex(self._prepare(tex), tex_template=RU,
                       font_size=s.get("size", BODY), color=s.get("color", TEXT))
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
        for n, m in zip(self.visible, mobs):
            s = self._style(n, line_styles, default)
            align = s.get("align", "center")
            x = 0 if align == "center" else (-6.3 if align == "left" else 6.3)
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
        if self._is_spacer(name):
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


def generate_module(scenes, preamble: str, title_info=None) -> str:
    header = (
        '"""СГЕНЕРИРОВАНО build.py — не редактировать."""\n'
        "import re\n"
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
        'RU = TexTemplate(preamble=r"""\n' + preamble + '\n""")\n\n'
        f"TITLE = {TITLE}\n"
        f"BODY = {BODY}\n"
        f"SUB = {SUB}\n"
    )
    parts = [header, SLIDE_CODE.strip(), ""]
    if has_title(title_info):
        parts.append(TITLE_CODE.strip())
        parts.append(f"class Title(TitleSlide):\n    data = {title_info!r}\n")
    for i, s in enumerate(scenes):
        parts.append(f"class Slide{i:02d}(Slide):\n    data = {s!r}\n")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# 8a. PDF-ВЕРСИЯ (раскадровка состояний; субтитры не включаются)
# ─────────────────────────────────────────────────────────────────────────────
def _pdf_prepare(tex: str) -> str:
    """Те же правила, что и в Slide._prepare: формула или текст."""
    if re.search(r"[А-Яа-яЁё]", tex):
        return tex
    t = tex.replace("$", "")
    envs = re.findall(r"\\begin\{([^}]+)\}", t)
    if any(e.strip() in MATH_ENVS for e in envs):
        return "\\[" + t + "\\]"
    m = re.match(r"^\{\\(Huge|LARGE|Large|large|huge)\s*(.*)\}$", t)
    if m:
        return "{\\" + m.group(1) + " $" + m.group(2) + "$}"
    if any(h in t for h in TEXT_HINTS):
        return t
    if not t.strip():
        return t
    return "$" + t + "$"


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
        if not content.strip():
            out.append(r"\par\vspace{0.4in}")
            continue
        out.append(_pdf_prepare(content) + r"\par\vspace{0.4in}")
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
        # страница 16:9, как кадр видео (14.22 × 8 дюймов)
        r"\geometry{paperwidth=36.1cm,paperheight=20.3cm,margin=1.2cm}",
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


def ask_output():
    """Выбор: видео, PDF или оба. Возвращает (видео, pdf)."""
    print("Что сгенерировать?")
    print("  1 — видео")
    print("  2 — PDF")
    print("  3 — и видео, и PDF")
    try:
        ans = input("Выбор (1/2/3) [3]: ").strip()
    except (EOFError, OSError):
        return True, False          # автоматический запуск: только видео
    if ans == "1":
        return True, False
    if ans == "2":
        return False, True
    return True, True               # "3" или пустой ввод


def _pdf_worker(result, fn, *args):
    result["ok"], result["msg"] = fn(*args)


# ─────────────────────────────────────────────────────────────────────────────
# 8. РЕНДЕР, СКЛЕЙКА, УБОРКА
# ─────────────────────────────────────────────────────────────────────────────
def valid_video(p: Path) -> bool:
    if not p.exists() or p.stat().st_size == 0:
        return False
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(p)],
        capture_output=True, text=True, errors="replace",
    )
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
    r = subprocess.run(cmd, cwd=HERE, capture_output=True)
    if r.returncode != 0:
        return name, False, _decode((r.stdout or b"") + (r.stderr or b""))

    found = list((work / "videos").rglob(f"{name}.mp4"))
    if not found:
        return name, False, f"после рендера не найден {name}.mp4"
    target = SLIDES_DIR / f"{name}.mp4"
    shutil.move(str(found[0]), str(target))
    if not valid_video(target):
        return name, False, f"{target.name} получился пустым"
    return name, True, ""


def render_parallel(names):
    SLIDES_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    failed = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
        futures = [ex.submit(render_one, n) for n in names]
        for fut in as_completed(futures):
            name, good, err = fut.result()
            if good:
                print(f"[готово] {name}", flush=True)
            else:
                ok = False
                failed.append(name)
                print(f"[ОШИБКА] {name}", flush=True)
                _print_latex_hint(err, name)
    if failed:
        print("Не удалось собрать: " + ", ".join(sorted(failed)))
    return ok


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
    r = subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(FINAL)],
        capture_output=True,
    )
    if r.returncode != 0:
        print("Ошибка ffmpeg при склейке:")
        print(_decode(r.stderr or b"")[-1500:])
        return False
    return valid_video(FINAL)


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
        ans = input("Использовать готовые видео из media/slides/ (y — доделать недостающие, n — очистить и собрать заново): ").strip().lower()
        return ans.startswith("y")
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


def main():
    print_banner()
    try:
        scenario = find_scenario()
        print(f"Сценарий: {scenario.name}")
        text = read_scenario_text(scenario)
        scenes, declared_pkgs, title_info = parse_scenario(text)
        packages = detect_packages(text) + declared_pkgs
        macros = extract_macros(_preamble_head(text))
        if macros:
            print(f"Пользовательских макросов: {len(macros)}")
        preamble = build_preamble(packages, macros)

        names = [f"Slide{i:02d}" for i in range(len(scenes))]
        if has_title(title_info):
            names = ["Title"] + names
            print("Титульный слайд: да")
        (HERE / GENERATED).write_text(
            generate_module(scenes, preamble, title_info), encoding="utf-8"
        )
    except ScenarioError as e:
        _fail(f"Ошибка сценария: {e}")
    except PermissionError as e:
        _fail(f"Нет доступа к файлу: {e}")
    except Exception as e:
        _fail(f"Не удалось прочитать сценарий: {e}")

    gen_video, gen_pdf = ask_output()
    if not gen_video and not gen_pdf:
        print("Ничего не выбрано.")
        _pause_exit()
        return

    # --- PDF (параллельно с видео) ---
    pdf_thread = None
    pdf_result = {"ok": False, "msg": ""}
    if gen_pdf:
        tex = build_handout_tex(scenes, title_info, packages, macros)
        HANDOUT_TEX.parent.mkdir(parents=True, exist_ok=True)
        HANDOUT_TEX.write_text(tex, encoding="utf-8")
        engine = find_local_latex()
        if engine:
            print(f"PDF: локальная компиляция ({engine}), без сети.")
            pdf_thread = threading.Thread(
                target=_pdf_worker,
                args=(pdf_result, compile_local, HANDOUT_TEX, engine),
                daemon=True,
            )
        else:
            print("Локальный LaTeX не найден.")
            print("Для PDF нужен доступ к сети: текст презентации будет отправлен")
            print("на сторонний сервер latexonline.cc (конфиденциальность не гарантируется).")
            try:
                ans = input("Продолжить онлайн-компиляцию? (y/n): ").strip().lower()
            except (EOFError, OSError):
                ans = "n"
            if ans.startswith("y"):
                pdf_thread = threading.Thread(
                    target=_pdf_worker,
                    args=(pdf_result, compile_online, HANDOUT_TEX, HANDOUT_PDF),
                    daemon=True,
                )
            else:
                print(f"PDF не собирался; исходник сохранён: {HANDOUT_TEX}")
        if pdf_thread:
            pdf_thread.start()

    # --- видео ---
    video_ok = True
    if gen_video:
        existing = [n for n in names if valid_video(SLIDES_DIR / f"{n}.mp4")]
        if existing:
            print(f"Готовых слайдов: {len(existing)} / {len(names)}")
        if not ask_continue():
            shutil.rmtree(SLIDES_DIR, ignore_errors=True)
            existing = []

        missing = [n for n in names if n not in existing]
        print(f"Всего сцен: {len(names)}, к рендеру: {len(missing)}")

        if missing:
            video_ok = render_parallel(missing)

        all_ready = all((SLIDES_DIR / f"{n}.mp4").exists() for n in names)
        if video_ok and all_ready:
            if concat(names):
                print(f"Цельное видео: {FINAL}")
            else:
                print("Не удалось собрать цельное видео.")
                video_ok = False
        else:
            print("Не все слайды готовы — цельное видео не собиралось.")

    # --- дождаться PDF ---
    if pdf_thread:
        pdf_thread.join()
        if pdf_result["ok"]:
            print(f"PDF: {HANDOUT_PDF}")
        else:
            print("PDF собрать не удалось.")
            if pdf_result["msg"]:
                print(pdf_result["msg"])

    cleanup()

    if gen_video and not video_ok:
        _fail("Сборка видео завершилась с ошибками.")

    print()
    print("=" * 60)
    print("  Готово!")
    if gen_video:
        print(f"  Слайды: {SLIDES_DIR}")
        print(f"  Видео:  {FINAL}")
    if gen_pdf:
        if pdf_result["ok"]:
            print(f"  PDF:    {HANDOUT_PDF}")
            print(f"  LaTeX:  {HANDOUT_TEX}")
        else:
            print(f"  LaTeX:  {HANDOUT_TEX} (PDF не собран)")
    print("=" * 60)
    _pause_exit()


if __name__ == "__main__":
    main()
