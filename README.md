# Notae

Notae turns a plain-text scenario into a timed teaching presentation. /
Notae собирает учебную презентацию из обычного текстового сценария.

[Русский](#русский) · [English](#english)

---

## Русский

**Notae** собирает учебную презентацию из обычного текстового сценария: вы
пишете сцены, строки, субтитры и задержки в привычном LaTeX-файле, а скрипт
рисует видео слайдов, склеивает его в цельный фильм и (по желанию) делает
PDF-раскадровку.

Слайды рисуются в [Manim Community](https://www.manim.community/) в
LaTeX-шрифте: кириллица — PT Serif, формулы — Computer Modern, заголовок —
ярко-жёлтый, фон тёмный. Формулы и текст можно писать прямо в сценарии.

**Содержание:** [Что нужно](#1-что-нужно) · [Быстрый старт](#2-быстрый-старт) ·
[Сценарий](#3-сценарий-за-пять-минут) · [Текст и формулы](#4-текст-формулы-и-диакритика) ·
[Длина и субтитры](#5-длина-строк-поля-и-субтитры) ·
[Служебные слова](#6-служебные-слова-и-фигурные-скобки) ·
[Проверка](#7-проверка-перед-сборкой) · [Оформление](#8-оформление-и-персонализация) ·
[PDF](#9-pdf-раскадровка) · [Интерактивный режим](#10-интерактивный-режим) ·
[Ошибки](#11-если-что-то-пошло-не-так) · [Структура](#12-структура-проекта) ·
[Лицензия](#13-лицензия)

### 1. Что нужно

- Python 3.9+
- [Manim Community](https://www.manim.community/): `pip install manim`
- `ffmpeg` — обычно ставится вместе с Manim
- LaTeX (MiKTeX на Windows или TeX Live): пакеты `amsmath`, `amssymb`,
  `amsthm`, `xcolor`, `paratype` (PT Serif)
- Для старого `.doc` (не `.docx`) — `antiword`, `catdoc` или LibreOffice

Проверить, что всё на месте, можно так:

```bash
manim --version
pdflatex --version
ffmpeg -version
```

---

### 2. Быстрый старт

1. Откройте `scenario.tex` рядом с `build.py` и отредактируйте его.
   Вместо него можно положить свой сценарий: `txt`, `md`, `tex`, `docx` или
   `doc`.
2. Запустите из терминала:

```bash
python build.py
```

3. Выберите, что собрать:

```
Что сгенерировать?
  1 — видео (MP4)
  2 — PDF (раскадровка)
  3 — интерактивная презентация (пока в разработке)
Видео и PDF можно совместить: введите 1,2.
```

- **1** — только видео;
- **2** — только PDF;
- **3** — заглушка будущего интерактивного режима (пока просто сообщение);
- **1,2** — и видео, и PDF.

4. Готовые файлы появятся в `media/`:

```
media/
  slides/
    Title.mp4       ← титульный слайд (если заполнено хотя бы одно его поле)
    Slide01.mp4     ← первый содержательный слайд
    Slide02.mp4     ← второй и т.д.
  final.mp4         ← все слайды по порядку
  handout.tex       ← LaTeX-исходник PDF-раскадровки
  handout.pdf       ← PDF-раскадровка
```

> **Имена слайдов.** Титульный слайд всегда называется `Title`, дальше идут
> `Slide01`, `Slide02`, … — **нумерация начинается с единицы**. Те же имена
> используются в терминале (`[готово] Slide01 (Название сцены)`), в списке
> ошибок и предупреждений и в именах файлов `media/slides/`. Отдельно придумывать имена
> файлам не нужно. Если ни одно поле титульного блока не заполнено, слайда
> `Title` нет, и нумерация начинается сразу с `Slide01`.

В конце скрипт печатает, что готово, и не закрывает окно сразу. Файл сценария
он не изменяет и сам себя не удаляет.

---

### 3. Сценарий за пять минут

Минимальный рабочий сценарий выглядит так:

```latex
title: {Название темы}
author: {Автор}
affiliation: {Организация}
event: {Мероприятие}
date: {Дата}
pause: 8.0

scene: {Пример сцены}

line l1: {Первая строка сценария.}
line l2: {$E = mc^2$}

sub s1: {Короткий субтитр.}

T: 8.0 l1
T: 5.0 l2
T: 6.0 s1
pause: 8.0
```

Что здесь что:

| Запись | Значение |
|---|---|
| `title`, `author`, `affiliation`, `event`, `date` | поля титульного слайда; любое можно опустить |
| `pause: 8.0` до первой сцены | сколько секунд держать титульный слайд |
| `scene: {…}` | новый слайд; заголовок необязателен (`scene: {}`) |
| `line имя: {…}` | строка, которая появляется по таймлайну |
| `sub имя: {…}` | субтитр внизу слайда |
| `T: 8.0 l1` | через 8 секунд после предыдущего действия показать `l1` |
| `T: 5.0 l1 -` | убрать строку `l1` |
| `T: 5.0 sub: -` | убрать субтитр |
| `pause: 5.0` | просто подождать 5 секунд |

Задержка в `T:` отсчитывается от **предыдущего действия**, а не от начала
слайда. Действия выполняются по порядку.

Комфортное среднее время между действиями — **5–10 секунд**. Оно зависит от
сложности предыдущего действия: короткой строке достаточно около 5 с, сложной
формуле или теореме — 7–10 с. Задержку 2–4 с используйте только для самой
первой строки сцены.

Строку можно объявить прямо в таймлайне, если она нужна один раз:

```latex
T: 5.0 line l9: {Строка, объявленная на месте.}
```

---

### 4. Текст, формулы и диакритика

Notae сам понимает, что перед ним:

- строка с обычными словами — **текст** (кириллица, английский, французский,
  немецкий — неважно);
- строка из математических команд и символов — **формула**;
- явная математика пишется через `$...$` или `\[...\]`.

```latex
line t1: {Обычный текст с формулой $E=mc^2$ внутри.}
line t2: {The quick brown fox jumps over the lazy dog.}
line t3: {naïve café, École normale, ñ и ü — это текст.}
line t4: {$\int_0^1 x^2\,dx = \frac13$}
```

Английский текст больше не превращается в формулу и переносится по словам.
Диакритика работает и в юникодном виде (`naïve`), и в латеховском
(`na\"ive`, `caf\'e`): строка всё равно распознаётся как текст.

Если сомневаетесь, оберните формулу в `$...$` явно — это всегда безопасно.

---

### 5. Длина строк, поля и субтитры

Поля презентации — **по 2 см слева и справа**. Длинная строка автоматически
переносится по словам и остаётся внутри полей; в PDF действуют те же поля.
Но злоупотреблять переносами не стоит: короткая строка читается лучше.

Ориентиры:

- одновременно видимых строк — примерно 6–7;
- субтитр — не более 3 строк;
- длинную мысль лучше разбить на несколько `line`, а не растягивать одну.

Перед сборкой Notae проверяет это и показывает ошибки и предупреждения
(подробнее в разделе 7). Субтитры рисуются внизу слайда; их перенос и
оформление уже настроены, менять для них ничего не нужно.

---

### 6. Служебные слова и фигурные скобки

Содержимое начинается с `{`. Дальше оно читается до **служебного слова в
начале новой строки**: `scene`, `line`, `sub`, `T`, `pause`, `title`,
`author`, `affiliation`, `event`, `date`, `package`/`packages`, `style`,
`common`.

Служебное слово обрывает содержимое **только если перед ним уже стоит
закрывающая `}`**. Пробелы, пустые строки и необязательный `\\` после `}` не
мешают. Благодаря этому внутри незакрытого `{...}` можно писать строки,
похожие на команды:

```latex
scene: {Фрагмент сценария}

line code: {Вот как выглядит таймлайн:\\
T: 8.0 l1\\
T: 5.0 l2\\
}

T: 6.0 code
```

Здесь `T:` внутри `line code` — обычный текст, потому что содержимое ещё не
закрыто. А в обычной записи закрывающая скобка стоит до `T:`:

```latex
line l1: {Текст}\\
T: 8.0 l1
```

`}` и `\\` можно ставить для красоты исходника — парсер это понимает.
Если содержимое так и не закрыто, а дальше начинается служебное слово, скрипт
выдаст понятную ошибку с номером строки.

Закрывающая `}` в конце содержимого необязательна только тогда, когда после
него нет служебного слова (например, содержимое — последнее в файле). Если
дальше идёт `T:`, `line`, `scene` и т.п. — закройте скобку явно.

Если содержимое само заканчивается на `}`, поставьте **две** закрывающие
скобки: `…}}` (или `…\}}`, если последняя скобка должна быть экранированной).
Иначе последняя `}` будет считаться закрывающей содержимое и отбросится.

---

### 7. Проверка перед сборкой

До первого `[готово]` Notae проверяет сценарий и делит результат на две
группы.

**Ошибки** — из-за них слайд (или весь PDF) может не собраться:

- ошибки LaTeX в реально используемых строках: неизвестная команда,
  незакрытое окружение, непарная скобка или `$`, отсутствующий символ шрифта.

**Предупреждения** — сборку не срывают, но слайд может выглядеть хуже:

- субтитр длиннее 3 строк;
- строка переносится из-за длины;
- строка не помещается по ширине даже с переносом;
- слишком много одновременно видимых строк: блок вылезает за рабочую область
  вверх или вниз;
- ошибка LaTeX в строке или субтитре, которые ни разу не используются
  (на сборку она не влияет).

Полный отчёт печатается один раз — перед первой сборкой. Сначала идут ошибки,
потом предупреждения; внутри каждого блока — по слайдам, затем по типу. В конце
печатаются списки слайдов: `Слайды с ошибками:` и
`Слайды с предупреждениями:`.

После отчёта скрипт ждёт Enter:

1. при ошибках — исправьте их и сохраните файл; предупреждения можно оставить;
2. нажмите Enter — Notae перечитает сценарий и проверит его снова;
3. **полный список перед рендерингом больше не печатается**. Выводится только
   краткая сводка: сколько осталось ошибок и предупреждений, и какие слайды
   затронуты ошибками. Затем начинается сборка — не редактируйте сценарий,
   пока она идёт.

После завершения сборки:

- если были **ошибки** или слайды/PDF не собрались — печатается краткий список
  ошибок и предложение исправить их и дособрать только изменившиеся слайды.
  Остальные ролики сохраняются. Если число сцен изменилось, инкрементальная
  сборка невозможна — скрипт сообщит об этом и предложит пересобрать всё заново;
- если остались **только предупреждения** — они кратко повторяются, но вопрос
  о пересборке **не задаётся**: сборка уже готова, а предупреждения её не
  срывают.

Пример краткой сводки перед рендерингом:

```
Остались ошибки: 1. Сборка начнётся; подробности — после её завершения.
Слайды с ошибками: Slide04 (Дифференциальное уравнение)
Не редактируйте сценарий во время сборки.
```

---

### 8. Оформление и персонализация

#### Стили строк и субтитров

```latex
common:
line gap: {\vspace{1.0cm}}

style default: size=36 color=TEXT anim=write align=center
style sub default: size=26 color=MUTED

style line l1: color=GOLD
style sub s1: size=24 align=left
```

| Ключ | Значения |
|---|---|
| `color` | `TEXT`, `MUTED`, `YELLOW`, `GOLD`, `BLUE`, `GREEN`, `RED`, `PURPLE` или `#RRGGBB` |
| `size` | размер шрифта (число) |
| `anim` | `write`, `fade`, `none` |
| `align` | `center`, `left`, `right` (края совпадают с полями) |

`style default` — для всех строк, `style sub default` — для всех субтитров.
`style line имя` и `style sub имя` переопределяют конкретную строку.

#### Общий блок

Всё, что объявлено до первой сцены, доступно во всех сценах:

```latex
common:
line gap: {\vspace{1.0cm}}
sub note: {Общий субтитр.}
style default: size=36 color=TEXT
```

Если в сцене объявить `line gap` заново, она переопределит общую.

#### Свои макросы и пакеты

В `.tex`-сценарии можно объявлять макросы в преамбуле — Notae перенесёт их в
генерируемый LaTeX:

```latex
\newcommand{\R}{\mathbb{R}}
\newcommand{\norm}[1]{\left\lVert #1 \right\rVert}
\DeclareMathOperator{\E}{E}
\newtheorem{lemma}{Лемма}
\newenvironment{note}{\begin{quote}\itshape}{\end{quote}}
```

Поддерживаются `\newcommand`, `\renewcommand`, `\providecommand`,
`\DeclareMathOperator`, `\newtheorem`, `\newenvironment`, `\renewenvironment`
и `\let`. Пакеты можно подключить так:

```latex
\usepackage{tikz}
```

или строкой сценария:

```latex
package: {amsthm, tikz}
```

Окружения `theorem`, `lemma`, `definition`, `corollary`, `proposition`,
`remark`, `example` и `proof` доступны сразу.

#### Цвета и акценты

Цвет — только для настоящих акцентов:

```latex
line l2: {$\mathbb{D}\left(\frac{S_n}{n}\right)=\frac{x(1-x)}{n}$. \quad {\color{red}\footnotesize (Проверьте!)}}
```

#### Отбивки

```latex
line gap: {\vspace{0.5cm}}
line x: {}
```

Пустая строка — невидимый разрыв между блоками, `\vspace` — отступ заданной
высоты.

---

### 9. PDF-раскадровка

PDF — это «раскадровка» презентации: одна страница на каждое состояние
слайда (после добавления или удаления строки; титульный слайд — отдельной
страницей). **Субтитры в PDF не входят.** Оформление повторяет видео:
страница 16:9, поля 2 см, тёмный фон, жёлтый заголовок, PT Serif, формулы
Computer Modern.

Компилятор выбирается так:

- если локальный LaTeX (`pdflatex` / `xelatex` / `lualatex`) есть — PDF
  собирается локально, без сети;
- иначе скрипт предупредит, что текст презентации будет отправлен на
  сторонний сервер `latexonline.cc`, и спросит согласие;
- при отказе или ошибке останется `media/handout.tex` — его можно
  скомпилировать где угодно (Overleaf, локальный TeX, онлайн).

`handout.tex` сохраняется всегда, когда запрошен PDF.

---

### 10. Интерактивный режим

Пункт меню **3** — заготовка будущего способа показа презентации в реальном
времени: слайды листаются в темпе докладчика, с управлением с клавиатуры,
заметками и таймером. Пока пункт показывает сообщение о разработке и ничего
не собирает. Для показа сейчас используйте видео или PDF.

---

### 11. Если что-то пошло не так

| Ситуация | Что делать |
|---|---|
| `в папке нет файла сценария` | положите рядом с `build.py` файл `scenario.tex`/`scenario.txt`/`scenario.md` |
| `не найдено ни одной сцены` | добавьте `scene: {…}` |
| `неизвестное имя «…» в T:` | проверьте имя строки/субтитра и опечатку |
| `удаляется неизвестная строка` | строка должна быть объявлена до `T: … -` |
| `содержимое «…» не закрыто` | закройте содержимое `}` перед `T:`/`line:`/`scene:` |
| `[ОШИБКА] SlideNN` + текст LaTeX | исправьте формулу/команду по подсказке |
| PDF не собрался | проверьте `media/handout.tex`; при необходимости скомпилируйте вручную |

Скрипт старается не удалять ваши результаты: перед повторной сборкой он
спрашивает, использовать ли готовые ролики, а временные файлы (`_scenes.py`,
`_work/`, кэш LaTeX) убирает сам.

---

### 12. Структура проекта

```
Notae/
  build.py       ← весь скрипт: парсер, тема, рендер, PDF, проверки
  README.md      ← этот файл
  scenario.tex   ← шаблон сценария: берите за основу
  skills/        ← инструкции для агентов: Beamer → Notae, LaTeX → Notae
  examples/      ← пример готовой презентации
  LICENSE
```

Все настройки рендера (качество, FPS, число параллельных процессов) и тема
(цвета, шрифты, размеры) — в начале `build.py`, в разделах `1. НАСТРОЙКИ` и
`2. ТЕМА`.

---

### 13. Лицензия

Notae распространяется по лицензии MIT. Подробности — в `LICENSE`. При
разработке использовалась модель ИИ компании DeepSeek (deepseek-flash);
лицензия MIT относится ко всему проекту.

## English

**Contents:** [What it is](#what-it-is) · [Requirements](#requirements) ·
[Quick start](#quick-start) · [Scenario basics](#scenario-basics) ·
[Text and formulas](#text-formulas-and-diacritics) ·
[Length and subtitles](#length-margins-and-subtitles) ·
[Service words](#service-words-and-braces) · [Checks](#checks-before-building) ·
[Customisation](#customisation) · [PDF](#pdf-storyboard) ·
[Interactive mode](#interactive-mode) · [Troubleshooting](#troubleshooting) ·
[Project layout](#project-layout) · [License](#license)

### What it is

Notae turns a plain-text scenario into a timed teaching presentation: it
renders the slides with [Manim Community](https://www.manim.community/) and
LaTeX, joins them into a single video and optionally builds a PDF storyboard.

The visual style is fixed by the project: dark background, PT Serif for text,
Computer Modern for formulas, a bright yellow scene title.

### Requirements

- Python 3.9+
- [Manim Community](https://www.manim.community/): `pip install manim`
- `ffmpeg` (usually installed together with Manim)
- LaTeX: MiKTeX on Windows or TeX Live, with `amsmath`, `amssymb`, `amsthm`,
  `xcolor`, `paratype` (PT Serif)
- For legacy `.doc` files (not `.docx`): `antiword`, `catdoc` or LibreOffice

Check the installation:

```bash
manim --version
pdflatex --version
ffmpeg -version
```

### Quick start

1. Edit `scenario.tex` next to `build.py`. You can also use your own
   `scenario.txt`, `scenario.md`, `scenario.tex`, `.docx` or `.doc`.
2. Run:

```bash
python build.py
```

3. Choose what to build:

```
Что сгенерировать?
  1 — видео (MP4)
  2 — PDF (раскадровка)
  3 — интерактивная презентация (пока в разработке)
Видео и PDF можно совместить: введите 1,2.
```

- `1` — video only;
- `2` — PDF only;
- `3` — the interactive presentation stub (a message for now);
- `1,2` — both video and PDF.

4. The result appears in `media/`:

```
media/
  slides/
    Title.mp4       ← title slide, if the title block is filled
    Slide01.mp4     ← first content scene
    Slide02.mp4     ← second scene, and so on
  final.mp4         ← all slides joined in order
  handout.tex       ← LaTeX source of the PDF storyboard
  handout.pdf       ← PDF storyboard
```

> **Slide names.** The title slide is always `Title`; content scenes are
> `Slide01`, `Slide02`, … — **numbering starts at 1**. The same names are used
> in the terminal (`[готово] Slide01 (Scene title)`), in the warnings and in
> `media/slides/`. If no title field is filled, there is no `Title` slide and
> numbering starts with `Slide01`.

The script does not modify your scenario and does not delete itself. At the
end it prints a short summary and asks you to press Enter before closing the
window.

### Scenario basics

A minimal scenario:

```latex
title: {Presentation title}
author: {Author}
affiliation: {Organisation}
event: {Event}
date: {Date}
pause: 8.0

scene: {Example scene}

line l1: {First line of the scenario.}
line l2: {$E = mc^2$}

sub s1: {A short subtitle.}

T: 8.0 l1
T: 5.0 l2
T: 6.0 s1
pause: 8.0
```

What the records mean:

| Record | Meaning |
|---|---|
| `title`, `author`, `affiliation`, `event`, `date` | title-slide fields; all optional |
| `pause: 8.0` before the first scene | how long the title slide stays on screen |
| `scene: {…}` | a new slide; the title is optional (`scene: {}`) |
| `line name: {…}` | a line that appears according to the timeline |
| `sub name: {…}` | a subtitle at the bottom of the slide |
| `T: 8.0 l1` | after 8 seconds from the previous action, show `l1` |
| `T: 5.0 l1 -` | remove line `l1` |
| `T: 5.0 sub: -` | remove the subtitle |
| `pause: 5.0` | simply wait 5 seconds |

A delay is measured from the **previous action**, not from the beginning of
the slide. Actions are executed in order.

A comfortable average delay between actions is **5–10 seconds**. Choose it from
the complexity of the previous action: a short line needs about 5 s, a complex
formula or theorem needs 7–10 s. Use 2–4 s only for the very first line of a
scene.

A line can be declared directly in the timeline when it is needed only once:

```latex
T: 5.0 line l9: {A line declared in place.}
```

### Text, formulas and diacritics

Notae decides automatically:

- a line with ordinary words is **text** — Cyrillic, English, French, German
  and accented Latin are treated the same way, regardless of the babel setup;
- a line made only of math commands and symbols is a **formula**;
- explicit math is written with `$...$` or `\[...\]`.

```latex
line t1: {Ordinary text with a formula $E=mc^2$ inside.}
line t2: {The quick brown fox jumps over the lazy dog.}
line t3: {naïve café, École normale, ñ and ü are text.}
line t4: {$\int_0^1 x^2\,dx = \frac13$}
```

English prose is no longer turned into a formula and wraps by words. Unicode
diacritics (`naïve`) and LaTeX accents (`na\"ive`, `caf\'e`) are both recognised
as text.

If in doubt, mark a formula explicitly with `$...$` — that is always safe.

### Length, margins and subtitles

The presentation margins are **2 cm left and right**. A long line is wrapped
automatically by words and stays inside the margins; in PDF the same margins
apply. Still, short lines read better.

Guidelines:

- about 6–7 simultaneously visible lines;
- a subtitle should not exceed 3 lines;
- split a long thought into several `line` records instead of stretching one.

Before building, Notae checks these rules and reports warnings. Subtitles are
rendered at the bottom of the slide; their wrapping and styling are already
configured and need no changes.

### Service words and braces

Content starts with `{`. It is read until a **service word at the beginning of
a new line**: `scene`, `line`, `sub`, `T`, `pause`, `title`, `author`,
`affiliation`, `event`, `date`, `package`/`packages`, `style`, `common`.

A service word terminates the content **only if a closing `}` stands before
it**. Spaces, blank lines and an optional `\\` after `}` are ignored. That is
why service-word-like lines can be literal text inside an unclosed `{...}`:

```latex
scene: {Fragment}

line code: {Here is the timeline:\\
T: 8.0 l1\\
T: 5.0 l2\\
}

T: 6.0 code
```

Here `T:` inside `line code` is ordinary text because the content is still
open. In a normal declaration the closing brace comes before `T:`:

```latex
line l1: {Text}\\
T: 8.0 l1
```

`}` and `\\` may be used for readability of the source; the parser understands
that. If the content is never closed before a real service word, Notae reports
a clear error with the line number.

The closing `}` at the end of content is optional only when no service word
follows (for example, the content is the last thing in the file). If `T:`,
`line`, `scene` etc. follows, close the brace explicitly.

If the content itself ends with `}`, write **two** closing braces (`…}}`, or
`…\}}` when the literal brace is escaped). Otherwise the last `}` is treated as
the content delimiter and removed.

### Checks before building

Before the first `[готово]`, Notae checks the scenario and splits the result
into two groups.

**Errors** — the slide (or the whole PDF) may fail to build:

- LaTeX errors in content that is actually used: unknown command, unclosed
  environment, unbalanced brace or `$`, missing font character.

**Warnings** — the build will succeed, but the slide may look worse:

- a subtitle longer than 3 lines;
- a line that wraps because of its length;
- a line that does not fit even after wrapping;
- too many simultaneously visible lines: the block overflows the working area;
- a LaTeX error in a line or subtitle that is never used.

The full report is printed once, before the first build. Errors come first,
then warnings; inside each block the order is by slide, then by type. At the
end the report lists the affected slides.

After the report the script waits for Enter:

1. if there are errors, fix them and save the file; warnings may be left as is;
2. press Enter — Notae re-reads the scenario and checks it again;
3. **the full list is not reprinted before rendering.** Only a short summary is
   printed: how many errors and warnings remain and which slides have errors.
   Then the build starts — do not edit the scenario while it is running.

After the build:

- if there were **errors**, or slides/PDF failed, a short error list is
  printed and you are offered to fix them and rebuild only the changed slides.
  The other videos are kept. If the number of scenes changed, incremental
  rebuild is impossible — the script reports it and offers a full rebuild;
- if only **warnings** remain, they are repeated briefly, but **no rebuild
  question is asked**: the build is already complete and warnings do not block
  it.

### Customisation

Styles for lines and subtitles:

```latex
common:
line gap: {\vspace{1.0cm}}

style default: size=36 color=TEXT anim=write align=center
style sub default: size=26 color=MUTED

style line l1: color=GOLD
style sub s1: size=24 align=left
```

| Key | Values |
|---|---|
| `color` | `TEXT`, `MUTED`, `YELLOW`, `GOLD`, `BLUE`, `GREEN`, `RED`, `PURPLE` or `#RRGGBB` |
| `size` | font size (number) |
| `anim` | `write`, `fade`, `none` |
| `align` | `center`, `left`, `right` (edges follow the margins) |

`style default` applies to all lines, `style sub default` to all subtitles.
`style line name` and `style sub name` override a single element.

Content declared before the first scene is shared by all scenes:

```latex
common:
line gap: {\vspace{1.0cm}}
sub note: {A shared subtitle.}
style default: size=36 color=TEXT
```

If a scene declares the same `line` again, it overrides the shared one.

User macros are supported in a `.tex` scenario:

```latex
\newcommand{\R}{\mathbb{R}}
\newcommand{\norm}[1]{\left\lVert #1 \right\rVert}
\DeclareMathOperator{\E}{E}
\newtheorem{lemma}{Lemma}
\newenvironment{note}{\begin{quote}\itshape}{\end{quote}}
```

Supported: `\newcommand`, `\renewcommand`, `\providecommand`,
`\DeclareMathOperator`, `\newtheorem`, `\newenvironment`, `\renewenvironment`
and `\let`. Packages can be loaded with `\usepackage{...}` anywhere in the
scenario or with:

```latex
package: {amsthm, tikz}
```

The environments `theorem`, `lemma`, `definition`, `corollary`,
`proposition`, `remark`, `example` and `proof` are available by default.

Empty lines and vertical gaps:

```latex
line gap: {\vspace{0.5cm}}
line x: {}
```

### PDF storyboard

PDF is a storyboard: one page per slide state (after adding or removing a
line; the title slide is a separate page). **Subtitles are not included.**
The layout mirrors the video: 16:9 page, 2 cm margins, dark background,
yellow title, PT Serif, Computer Modern formulas.

The compiler is chosen automatically:

- a local LaTeX (`pdflatex` / `xelatex` / `lualatex`) is used when available —
  no network;
- otherwise the script warns that the presentation text will be sent to
  `latexonline.cc` and asks for consent;
- if you decline or compilation fails, `media/handout.tex` remains and can be
  compiled anywhere (Overleaf, local TeX, an online service).

`handout.tex` is always saved when PDF is requested.

### Interactive mode

Menu item `3` is a placeholder for a future real-time presentation mode:
keyboard-driven slides, presenter notes and a timer. For now it only prints a
message and builds nothing. Use video or PDF for presenting.

### Troubleshooting

| Situation | What to do |
|---|---|
| `в папке нет файла сценария` | put `scenario.tex` / `scenario.txt` / `scenario.md` next to `build.py` |
| `не найдено ни одной сцены` | add `scene: {…}` |
| `неизвестное имя «…» в T:` | check the line/subtitle name and typos |
| `удаляется неизвестная строка` | declare the line before `T: … -` |
| `содержимое «…» не закрыто` | close the content with `}` before `T:` / `line:` / `scene:` |
| `[ОШИБКА] SlideNN` plus LaTeX text | fix the formula/command using the hint |
| PDF was not built | inspect `media/handout.tex` and compile it manually if needed |

The script tries not to delete your results: before a repeated build it asks
whether to reuse existing videos, and it removes only temporary files
(`_scenes.py`, `_work/`, LaTeX cache).

### Project layout

```
Notae/
  build.py       ← parser, theme, renderer, PDF and checks
  README.md      ← this file
  scenario.tex   ← scenario template
  skills/        ← agent instructions: Beamer → Notae, LaTeX → Notae
  examples/      ← a pre-built example presentation
  LICENSE
```

Rendering settings (quality, FPS, parallel jobs) and the theme (colours, fonts,
sizes) are at the top of `build.py`, sections `1. НАСТРОЙКИ` and `2. ТЕМА`.

### License

MIT. See `LICENSE`. The project was developed with assistance from an AI model
by DeepSeek (model: deepseek-flash); the MIT license applies to the whole
project.

---
