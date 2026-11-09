---
name: notae-scenario-from-beamer
description: Convert a Beamer LaTeX presentation into a Notae scenario.tex file. Use when the user provides a Beamer .tex source (or asks to turn a Beamer talk into Notae scenario, Manim video, or timed teaching slides) and needs a complete scenario.tex that follows the Notae markup rules for scenes, lines, subtitles, timing and styles.
---

# Notae Scenario from Beamer

Transform a Beamer presentation into a ready-to-use `scenario.tex` for the Notae
project (https://github.com/FABSEN1/Notae/). The output must be a self-contained
`.tex` file that Notae's `build.py` can turn into timed Manim video slides and a
PDF storyboard.

## Primary use-case

The user has a `beamer.tex` (or a single `\begin{frame}` block) and wants a
Notae scenario. Typical requests:

- “Переведи эту Beamer-презентацию в Notae”
- “Сделай сценарий по этому слайду”
- “Убери из Beamer тему/навигацию, оставь только слайды”

If the user gives only one frame, do just that frame. If they give the whole
talk, do the whole talk but still apply the density rules below.

---

## I. Shared Notae rules (identical to the LaTeX/paper skill)

### Slide names — mandatory marker comments

Notae names the slides itself and the names are identical in the terminal, in
warnings and in `media/slides/`:

| Slide | Name |
|---|---|
| title slide (if at least one field is filled) | `Title` |
| first scene | `Slide01` |
| second scene | `Slide02` |
| … | … (numbering starts at **1**, never `Slide00`) |

**Every scene must be preceded by a marker comment with the actual Notae
slide name.** This is how the user navigates the file when proof-reading or
debugging a single slide. Use exactly this form:

```latex
%--------------- Title ---------------


title: {…}
author: {…}


%--------------- Slide01 ---------------


scene: {…}

line l1: {…}
…


%--------------- Slide02 ---------------


scene: {…}
```

Rules for the marker:

- Begins at column 1, `%` followed by dashes, ` Title ` or ` SlideNN `, dashes
  to the end.
- The name must match what Notae will actually print: `Title`, `Slide01`,
  `Slide02`, … (never `Slide1`, `Slide00`, `Scene_1`, `TitleSlide`).
- The number inside `SlideNN` is determined **only** by the order of `scene:`
  blocks — count them as you generate.
- If a scene is added, removed or reordered later, renumber the markers.
- The marker is a comment, so pdflatex ignores it; it does **not** replace the
  “two blank lines after `scene:`”.

In chat, when referring to a specific slide, use the form
`Slide04 (Дифференциальное уравнение)` — number plus scene title. Do not
promise `SlideNN.pdf`: the PDF storyboard has pages, not per-slide files.

### Text, formulas, English, diacritics

- A line with ordinary words is text. This is script-independent: Cyrillic,
  English, French, German and accented Latin are treated the same way, no
  matter which babel is declared.
- A line made only of math commands/symbols is a formula.
- Write English prose as plain text, **not** as `$English sentence$`.
- Explicit math should be marked with `$...$` or `\[...\]`.
- Unicode diacritics (`naïve`, `café`, `ñ`) and LaTeX accents (`na\"ive`,
  `caf\'e`) are both recognised as text, but in the source code **prefer
  LaTeX accents** (`caf\'{e}`) — Unicode combining marks sometimes fail
  in the LaTeX pipeline.

### Length, margins and density — hard limits

The presentation margins are **2 cm left and right**; long lines wrap
automatically in both video and PDF, and wrapped lines look bad and trigger a
pre-build warning. Treat density as a hard constraint, not a suggestion.

**Hard limits (do not exceed without splitting the scene):**

| Metric | Limit |
|---|---|
| Simultaneously visible `line` blocks in one scene | **≤ 7** |
| Physical rows on screen after wrapping (≈90 characters per row at 2 cm margins and 36 pt) | **≤ 10** |
| Subtitle length | **≤ 3 rows** |
| `line` that already wraps to a second physical row | split into two `line`s, or shorten |
| Width of a single formula | must fit ≤ 2/3 of the text area |

**How to estimate.** Beamer frames are typeset at ~10–11 pt; Notae is at 36 pt
with the 2 cm margins. A Beamer frame that looks sparse can easily overflow
in Notae. Before writing a scene, sketch how many physical rows each `line`
takes once typeset at size 36 with `align=center` inside a 2 cm-margined
frame. If the total exceeds 10 rows, split the scene. Common mistakes:

- A chain `A = B = C = D` written as one `line` wraps to 2–3 rows — split it.
- Long `\begin{pmatrix}…\end{pmatrix}` usually needs its own scene.
- A `line` starting with `\textbf{Утверждение.}` plus a formula is almost
  always 2 rows — either put the label on its own `line` (small size) or drop
  it into a `sub`.
- Lists of cases / `\quad`-separated items easily overrun — one item per `line`.

**Subtitle = spoken track.** When it grows past 3 rows, split it into two
`sub`s or move one sentence to the next scene. Do **not** remove subtitles
with `T: … sub: -`; when the scene ends, the subtitle disappears on its own.

**Errors vs warnings.** Notae distinguishes **errors** (LaTeX in used content;
they can fail the build) from **warnings** (long lines, subtitles, density).
Warnings never fail the build and do not require a rebuild; only errors should
be presented to the user as blocking.

### Preamble skeleton

```latex
\documentclass[a4paper,11pt]{article}

% --- кириллица и шрифты ---
\usepackage{cmap}
\usepackage[T2A]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage[russian]{babel}   % or the language of the source

\usepackage{amsmath, amsfonts, amssymb, amsthm}
\usepackage{mathrsfs}
\usepackage{geometry}
\usepackage{xcolor}

% --- user macros transferred from Beamer ---
% (paste here)

\begin{document}
```

Transfer only packages and macros that are actually used in the extracted
fragment (`amsmath`, `amssymb`, `amsthm`, `mathtools`, `mathrsfs`, `xcolor`,
`tikz` if present, font packages for Cyrillic). Ignore pure bibliography,
hyperref navigation, geometry fine-tuning, etc.

### Macro clash guard

Beamer sources frequently redefine LaTeX built-ins (`\Re`, `\Im`, `\vec`,
`\div`, `\S`, `\P`, …) via `\renewcommand` or `\let`. Two rules:

- If the source uses `\renewcommand` for a built-in, keep it **after** all
  `\usepackage` lines, but consider renaming (`\Re` → `\Real`, `\Rdet`) unless
  the whole talk relies on the override.
- A `\newcommand{\X}` that clashes with an already-defined `\X` surfaces as
  `Command \X already defined` in the Notae build log. Prefer `\providecommand`
  or a distinct name.

### Timing table (seconds)

**Main rule: the average time between actions is 5.0–10.0 seconds.** The delay
is chosen by how complex the **previous** action was — how long the viewer
needs to read it — not by the next action. A short line needs about 5 s; a
complex formula, definition or theorem needs 7–10 s. Intervals of 1–2 s are
reserved only for the very first appearance in a scene.

| Previous action | Delay before the next action |
|---|---|
| First content `line` of a scene (scene just appeared) | 2.0–4.0 |
| Short line or simple formula | 4.0–6.0 |
| Ordinary line with text or formula | 5.0–7.0 |
| Complex formula, definition, multi-line block | 7.0–10.0 |
| Significant theorem or key statement | 8.0–10.0 |
| Subtitle that explains a hard step | 7.0–10.0 |
| Final pause of a scene | 8.0–10.0 |

The first-line row is the minimum after the scene appears; if that first line
is itself a complex formula or theorem, use 7–10 s. A general subtitle that
just comments can use 4–6 s; 7–10 s is for a subtitle explaining a hard step.
Individual intervals may drop to 3–4 s only for a quick continuation; the
**mean across the scene** must still stay in 5–10 s — compensate with longer
holds after complex content and at the end of the scene.

If the Beamer source already has overlay specs (`\pause`, `\uncover<n->`,
`\onslide<n->`, `<n->`), treat them as hints for ordering, but always assign
concrete numeric delays. When in doubt, prefer longer delays. A formula that
takes the viewer 3 s to parse should stay on screen for at least that long
before the next line, and the interval after it should be 7–10 s.

### Default styles in `common:`

```latex
common:
line gap: {\vspace{1.0cm}}

style default: size=36 color=TEXT anim=write align=center
style sub default: size=26 color=MUTED
```

### Strict layout rules for scenes

When the `scenario.tex` is later compiled with ordinary pdflatex for
proof-reading, correct blank lines make the source readable. Follow these
rules **exactly**:

1. After the marker comment (`%------ SlideNN ------`) leave **two blank
   lines**.
2. After the line `scene: {…}` leave **two blank lines**.
3. Between two consecutive `line …` declarations leave **one blank line**.
4. After the last `line` and before the first `sub` leave **two blank lines**.
5. Between two consecutive `sub …` declarations leave **one blank line**.
6. After the last `sub` (or after the last `line` if there are no subs) and
   before the first `T:` leave **two blank lines**.
7. Between consecutive `T:` / `pause:` commands leave **one blank line**.
8. After the final `pause:` of a scene leave **two blank lines** before the
   next marker comment.

### Service words inside `{…}`

A line that starts with a service word (`scene`, `line`, `sub`, `T`, `pause`,
`title`, …) terminates the content **only if a closing `}` already stands
before it**. Spaces, blank lines and an optional `\\` after the `}` are
ignored.

- Normal scenes must close the content before the next `T:` / `line:` /
  `scene:`.
- Service-word-like lines can be shown as literal text while the `{…}` is not
  yet closed.
- If the content itself ends with `}`, write **two** closing braces (`…}}`,
  or `…\}}` when the literal brace is escaped); otherwise the last `}` is
  treated as the content delimiter and dropped.
- A service word that appears in the middle of a line (not at its start) does
  **not** close the content.

---

## II. Beamer-specific rules

### 2.1. What to extract from the Beamer preamble

**Packages to keep** (only those actually used in the extracted content):

| Package | Why |
|---|---|
| `cmap`, `fontenc` with `T2A`, `inputenc` with `utf8`, `babel` with the language | Cyrillic / language support |
| `amsmath`, `amssymb`, `amsthm`, `mathtools` | math |
| `mathrsfs` | if `\mathscr` is used |
| `xcolor` | if `\textcolor`, `\colorbox`, `\definecolor` are used |
| `graphicx` | only if `\includegraphics` appears in the kept frames |
| `tikz` / `pgfplots` | only if actually used in the kept frames |

**Packages to drop** (presentation-only):

`beamer`, `beamerarticle`, any `beamertheme*` / `beamercolortheme*` /
`beamerfonttheme*` / `beamerinnertheme*` / `beameroutertheme*`, `pgfpages`,
`handoutWithNotes`, `multimedia`, `movie15`, `media9`, `animate`, `hyperref`
(navigation), `appendixnumberbeamer`, `ragged2e` (unless it redefines a
command you need).

**Macros to transfer** (paste verbatim into the new preamble):

- `\newcommand`, `\renewcommand`, `\providecommand` (with optional-argument
  forms),
- `\DeclareMathOperator`, `\DeclareMathOperator*`,
- `\newtheorem`, `\newtheorem*`,
- `\newenvironment`, `\renewenvironment`,
- `\let`.

Do **not** transfer macros that depend on Beamer internals (`\alert`,
`\pause`, `\only`, `\onslide`, `\uncover`, `\visible`, `\invisible`,
`\alt`, `\temporal`, `\beamertemplate...`). These are stripped at the frame
level (section 2.2), and macros built on top of them either disappear or must
be manually rewritten.

### 2.2. Beamer commands to replace or strip

Beamer has presentation commands that have no meaning in Notae. Replace them
as follows:

| Beamer | Notae |
|---|---|
| `\alert{X}` | `\textbf{X}`, or `\textcolor{red}{X}` if the emphasis is important |
| `\structure{X}` | `\textcolor{blue}{X}` or just `X` |
| `\pause` | remove; the next `line` gets its own `T: delay nextline` |
| `\uncover<n->{X}` | `X` on its own `line` with a `T:` delay |
| `\only<n->{X}` | same |
| `\onslide<n->{X}` | same |
| `\visible<n->{X}` | same |
| `\invisible{X}` | `X` becomes a separate `line` that appears later |
| `\alt<n>{A}{B}` | `A` and `B` on separate `line`s with `T: A -` and `T: B` (rare), or two scenes |
| `\temporal<...>{A}{B}{C}` | three scenes, or `T: A -` + `T: B` + `T: B -` + `T: C` (rare) |
| overlay `<n->` on frame title | strip |
| `\begin{frame}[fragile]` | ignore the option |

The `<n->` overlay specs inside `\item<2->`, `\only<3->{...}` etc. become
numeric `T:` delays on the corresponding `line`. Do **not** keep any
`\pause`, `\uncover`, `\only`, `\onslide`, `\visible`, `\invisible`, `\alt`
or `\temporal` in the final file.

### 2.3. Title block from Beamer

| Beamer command | Notae field |
|---|---|
| `\title{X}` | `title: {X}` |
| `\subtitle{Y}` | append to `title`: `title: {X\\Y}`, or place in `event` |
| `\author{Z}` | `author: {Z}` |
| `\institute{W}` | `affiliation: {W}` |
| `\date{V}` | `date: {V}` |
| `\titlegraphic{…}` | ignore (Notae has no title graphic) |
| `\begin{frame}\titlepage\end{frame}` or `\maketitle` | **the `Title` block**, not a scene |

Emit the title block only if at least one field is meaningful. `pause: 8.0`
(or `10.0`) after the block is standard.

### 2.4. Frame → scene mapping

| Beamer | Notae |
|---|---|
| `\begin{frame}{Title}…\end{frame}` with real content | `scene: {Title}` + lines / subs / timeline |
| `\begin{frame}…\end{frame}` without a title | `scene: {}` |
| `\begin{frame}\titlepage\end{frame}` | `Title` block, not a scene |
| `\begin{frame}\tableofcontents\end{frame}` | skip, or a single-line outline scene if the user asks |
| Section-outline frames auto-inserted by themes (`\AtBeginSection`) | skip |
| `\begin{frame}<handout:0>` | skip |
| Backup slides (`[noframenumbering]` after `\appendix`) | skip unless the user asks |
| Thanks frame (`\begin{frame}\Huge Thanks!\end{frame}`) | final `scene: {}` with `\Huge Спасибо за внимание!` |

Strip overlay specs from frame titles: `\frametitle{X}<2->` → `scene: {X}`.

If the user asked for a specific frame, ignore the rest.

### 2.5. Linearizing blocks, columns, lists

Beamer's layout primitives have no direct Notae equivalent. Flatten them:

**`\begin{block}{Title}Body\end{block}`** — two `line`s:
`line b0: {\textbf{Title}}` (or use `sub`) followed by `line b1: {Body}`.
If the body is short (≤ 30 characters), one `line` is fine:
`line b1: {\textbf{Title.} Body}`.

**`\begin{block}{}Body\end{block}`** (no title) — just the body as `line`s.

**`\begin{columns}…\end{columns}`** — linearize: first-column lines, then
second-column lines. If both columns are dense, split into two scenes. Do
**not** try to reproduce the two-column layout.

**`\begin{itemize}` / `\begin{enumerate}`** — one `line` per item. Very short
items (≤ 20 characters) may share a `line` separated by `\quad`, but never
keep `\begin{itemize}…\end{itemize}` as a single `line`: at 36 pt with
`align=center` it will overflow.

**`\begin{description}`** — one `line` per item, with `\textbf{Term.}` at the
start.

**`\begin{theorem}` / `\lemma` / `\definition` / `\corollary` /
`\proposition` / `\remark` / `\example` / `\proof`** — see 2.6.

### 2.6. Theorem environments

Notae pre-defines `theorem`, `lemma`, `definition`, `corollary`,
`proposition`, `remark`, `example`, `proof`. Two options:

- **Flatten** for short statements:
  `line t1: {\textbf{Теорема (Вейерштрасс).} Для любой $f\in C[a,b]$ …}`.
- **Keep the environment** for multi-line proofs or when the visual box is
  wanted:
  `line t1: {\begin{theorem}Если $a=b$, то $b=a$.\end{theorem}}`.

In both cases the theorem label goes inside the `line` — do **not** emit
`\begin{theorem}` as a separate `line` from the body.

### 2.7. Code listings and verbatim

Beamer frames with `verbatim`, `lstlisting`, `minted` or `\begin{verbatim}`
have no clean Notae equivalent: Manim cannot typeset code as code. Two
options:

- **If the code is short (≤ 5 lines)**: convert to a `line` with
  `\texttt{...}` and `\\` between lines. This is fragile — escape special
  characters (`\{`, `\}`, `\%`, `\&`, `\#`, `\_`).
- **If the code is long or central to the talk**: replace the listing with a
  **description** in prose — what the code does, what the key step is. A
  frame with a 20-line listing becomes a “что делает алгоритм” scene, not a
  “вот код” scene.

Never promise the user that the code listing will be rendered as code.

---

## III. Workflow (algorithmic, follow in order)

### Step 1. Inventory the frames

Open the source and list every `\begin{frame}` in order. For each, note:

- title (or empty),
- class: title page / table of contents / section outline / real content /
  thanks / backup,
- a short content sketch (bullet count, formula count, overlay count),
- packages and macros that appear inside the frame (so you can decide what
  to keep in the preamble).

### Step 2. Extract the preamble

Per section II.1: keep the packages and macros that the kept content
actually uses; drop the rest. Note the title / author / institute / date /
event fields for the title block.

### Step 3. Emit the title block

If at least one field is meaningful, emit:

```latex
%--------------- Title ---------------


title: {…}
author: {…}
affiliation: {…}
event: {…}
date: {…}
pause: 8.0
```

### Step 4. Map frames to scenes; sketch the list

Per sections II.3–II.4: assign each substantive frame a `SlideNN`, skip
title page / table of contents / section outlines / backups. List scenes as
short titles:

```
Title
Slide01. …
Slide02. …
…
```

### Step 5. Resolve overlays and linearize

For each frame: replace `\alert`, `\pause`, `\uncover`, `\only`, `\onslide`,
`\visible`, `\invisible`, `\alt`, `\temporal` per section II.2. Linearize
`block`, `columns`, `itemize`, `description` per section II.5. Flatten or
keep theorem environments per section II.6. Handle code listings per
section II.7.

### Step 6. Estimate density; decide splits

For each scene: count `line`s and estimate physical rows. If > 7 visible
`line`s or > 10 physical rows, **split into two scenes** at a natural
boundary. If the frame's final overlay state alone would exceed 7 lines,
split. Do not squeeze.

If a frame has overlays that reveal 3 items and the final state is 7 lines,
that is fine — emit all 7 with `T:` delays. If the final state is 9 lines,
split into two scenes.

### Step 7. Write lines, subs, timeline

- One `line` per logical statement, formula or list item.
- Subtitles ≤ 3 rows, spoken voice, not a copy of the lines.
- Timeline per the timing table. No `T: … sub: -`.
- Colour only for genuine emphasis (`{\color{red} \footnotesize (Проверьте!)}`).

### Step 8. Compose the file

Emit in this order:

1. preamble (packages actually used + macros transferred from Beamer),
2. `\begin{document}`,
3. `common:` block with default styles,
4. `Title` marker + title block if any field is meaningful,
5. for each scene: marker comment (`%------ SlideNN ------`) →
   `scene:` → lines → subs → timeline → final pause,
6. final “Спасибо” scene if appropriate,
7. `\end{document}`.

### Step 9. Pre-output self-check (block release until it passes)

| # | Check | Pass criterion |
|---|---|---|
| 1 | Marker comments | `%------ Title ------` before the title block (if any) and `%------ SlideNN ------` before each scene, numbered consecutively from 1 |
| 2 | Density | every scene ≤ 7 visible `line`s and ≤ 10 physical rows estimated |
| 3 | Wrapping | no `line` that will visibly wrap; long formulas split |
| 4 | Subtitle | every `sub` ≤ 3 rows |
| 5 | No `T: … sub: -` | subtitles never explicitly removed |
| 6 | Overlays resolved | no `\pause`, `\uncover`, `\only`, `\onslide`, `\visible`, `\invisible`, `\alt`, `\temporal`, `\alert`, `\structure` left in the file |
| 7 | Balancing | every `{…}` closed before the next service word |
| 8 | Escape | every formula inside `$…$` / `\[…\]`; English prose not wrapped in `$` |
| 9 | Macro clashes | any `\renewcommand` that overrides a built-in is justified, otherwise rename |
| 10 | Diacritics | LaTeX accents (`caf\'{e}`) in code, not raw Unicode combining chars |
| 11 | Timing | mean delay between actions 5.0–10.0 s; first content line ≥ 2.0 s; complex/theorem ≥ 7.0 s; final pause ≥ 8.0 s |
| 12 | Blank-line layout | rules 1–8 from “Strict layout” hold for every scene |
| 13 | Preamble | only used packages and macros are present; Beamer-only packages dropped |
| 14 | Layout linearized | no `\begin{block}`, `\begin{columns}`, `\begin{itemize}` left in the file |

Only after all 14 pass, return the file.

---

## IV. Examples (non-ideal, for reference)

These fragments illustrate the mechanics of conversion. They are **not** a
model course, a typical talk, or a template to copy verbatim: always adapt the
topics to the user's own material. The intervals are illustrative; keep the
mean delay at 5–10 s as described in the timing table.

### Example A. Title block from Beamer

Beamer source:

```latex
\title{Название темы}
\subtitle{Подзаголовок}
\author{Автор}
\institute{Организация}
\date{Дата}
\begin{document}
\begin{frame}\titlepage\end{frame}
```

Becomes:

```latex
%--------------- Title ---------------


title: {Название темы\\Подзаголовок}
author: {Автор}
affiliation: {Организация}
date: {Дата}
pause: 8.0
```

The `\titlepage` frame itself is **not** a scene.

### Example B. Simple frame → simple scene

Beamer source:

```latex
\begin{frame}{Мотивация}
  \begin{itemize}
    \item Существуют и используются полугруппы, не являющиеся сильно
          непрерывными;
    \item Потребность работы не только в нормируемых, но и в локально
          выпуклых пространствах.
  \end{itemize}
\end{frame}
```

Becomes:

```latex
%--------------- Slide01 ---------------


scene: {Мотивация}


line l1: {Существуют и используются полугруппы, не являющиеся сильно непрерывными.}

line l2: {Потребность работы не только в нормируемых, но и в локально выпуклых пространствах.}


sub s1: {Мотивация: сильно непрерывных полугрупп недостаточно для приложений.}


T: 2.0 l1

T: 4.0 l2

T: 4.0 s1

pause: 8.0
```

### Example C. Theorem frame → scene (density near the limit)

Beamer source:

```latex
\begin{frame}{Теорема Вейерштрасса}
  \begin{theorem}[Вейерштрасс, 1885]
    Для любой $f \in C[a,b]$ и любого $\varepsilon>0$
    существует многочлен $P$ такой, что
    $\|f - P\|_{C[a,b]} < \varepsilon$.
  \end{theorem}
  Иными словами, многочлены всюду плотны в $C[a,b]$.
\end{frame}
```

Becomes:

```latex
%--------------- Slide02 ---------------


scene: {Теорема Вейерштрасса}


line l1: {\textbf{Теорема} (Вейерштрасс, 1885).}

line l2: {Для любой $f \in C[a,b]$ и любого $\varepsilon>0$}

line l3: {существует многочлен $P$ такой, что}

line l4: {$\|f - P\|_{C[a,b]} < \varepsilon.$}

line l5: {Иными словами, многочлены всюду плотны в $C[a,b]$.}


sub s1: {Формулировка дана для произвольного отрезка. Доказательство проведём для $[0,1]$.}


T: 8.0 l1

T: 3.0 l2

T: 2.0 l3

T: 5.0 l4

T: 3.0 l5

T: 4.0 s1

pause: 10.0
```

### Example D. Overlay-heavy frame → split into two scenes

Beamer source (final overlay state has 9 visible items — too many for one
Notae scene):

```latex
\begin{frame}{Практическая значимость}
  \begin{itemize}
    \item<1-> Некорректно поставленная задача Коши;
    \item<2-> Работа с сопряжёнными полугруппами;
    \item<3-> Приложения к динамическим системам;
    \item<4-> Приложения в теории марковских процессов;
    \item<5-> Приложения в квантовой механике;
    \item<6-> Полугруппы квантовых каналов;
    \item<7-> Implemented semigroups;
    \item<8-> Сопряжённые полугруппы в слабой топологии;
    \item<9-> Сопряжённые полугруппы в сильной топологии.
  \end{itemize}
\end{frame}
```

Becomes:

```latex
%--------------- Slide04 ---------------


scene: {Практическая значимость (1)}


line p1: {Некорректно поставленная задача Коши.}

line p2: {Работа с сопряжёнными полугруппами.}

line p3: {Приложения к динамическим системам.}

line p4: {Приложения в теории марковских процессов.}

line p5: {Приложения в квантовой механике.}


sub s1: {Практическая значимость.}


T: 2.0 p1

T: 4.0 p2

T: 4.0 p3

T: 4.0 p4

T: 4.0 p5

T: 4.0 s1

pause: 10.0


%--------------- Slide05 ---------------


scene: {Практическая значимость (2)}


line p1: {Полугруппы квантовых каналов.}

line p2: {Implemented semigroups.}

line p3: {Сопряжённые полугруппы в слабой топологии.}

line p4: {Сопряжённые полугруппы в сильной топологии.}


sub s1: {Продолжение списка применений.}


T: 2.0 p1

T: 4.0 p2

T: 4.0 p3

T: 4.0 p4

T: 4.0 s1

pause: 10.0
```

### Example E. Itemize → one line per item

Beamer source:

```latex
\begin{frame}{Диофантовы уравнения}
  а) Решите в целых числах уравнение $21x+76y=0$.\\
  б) Решите в целых числах уравнение $21x+76y=1$.\\
  Сколько решений $(x_0,y_0)$ удовлетворяют условию $0\le x_0\le 75$?\\
  в) В кольце $\mathbb{Z}_{76}$ вычислите $[21]_{76}^{-1}$.
\end{frame}
```

Becomes:

```latex
%--------------- Slide06 ---------------


scene: {Диофантовы уравнения}


line l1: {а) Решите в целых числах уравнение $21x+76y=0$.}

line l2: {б) Решите в целых числах уравнение $21x+76y=1$.}

line l3: {Сколько решений $(x_0,y_0)$ удовлетворяют условию $0\le x_0\le 75$?}

line l4: {в) В кольце $\mathbb{Z}_{76}$ вычислите $[21]_{76}^{-1}$.}


sub s1: {Линейные уравнения в кольцах $\mathbb{Z}$ и $\mathbb{Z}_{76}$.}


T: 2.0 l1

T: 4.0 l2

T: 4.0 l3

T: 4.0 l4

T: 4.0 s1

pause: 8.0
```

### Example F. Code listing → text description

Beamer source (with `[fragile]` and a long listing):

```latex
\begin{frame}[fragile]{Алгоритм Евклида}
\begin{verbatim}
while b != 0:
    a, b = b, a % b
return a
\end{verbatim}
\end{frame}
```

Becomes (the listing is replaced by its idea — Manim cannot typeset code):

```latex
%--------------- Slide07 ---------------


scene: {Алгоритм Евклида}


line l1: {Пока $b \neq 0$: заменяем $(a,b)$ на $(b,\ a \bmod b)$.}

line l2: {Возвращаем $a$.}


sub s1: {Алгоритм Евклида: на каждом шаге остаток от деления уменьшает второе число.}


T: 2.0 l1

T: 4.0 l2

T: 4.0 s1

pause: 8.0
```

Never promise that the listing will be rendered as code.

### Example G. Final thanks

Beamer source:

```latex
\begin{frame}
  \centering
  \Huge Спасибо за внимание!
\end{frame}
```

Becomes:

```latex
%--------------- Slide08 ---------------


scene: {}


line e1: {\Huge Спасибо за внимание!}

style line e1: size=60 color=YELLOW


pause: 10.0
```

---

## Output

Always produce a complete, self-contained `scenario.tex` that the user can
drop next to `build.py` and run. Do not emit Python or Manim code; the
scenario is the only deliverable. Every scene must carry its
`%------ SlideNN ------` marker, and the file must pass the Step 9
self-check before it is returned.
