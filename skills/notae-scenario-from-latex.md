---
name: notae-scenario-from-latex
description: Convert a standard LaTeX document (article, book chapter or lecture notes) into a Notae scenario.tex. Use when the user asks to turn a paper, notes or a selected story/plot from continuous LaTeX prose into timed teaching slides, Manim video or Notae presentation. Prefer extracting one coherent narrative rather than the whole document.
---

# Notae Scenario from LaTeX Document

Turn a continuous LaTeX source (article, book, lecture notes) into a ready-to-use
`scenario.tex` for the Notae project (https://github.com/FABSEN1/Notae/).
Unlike the Beamer-to-Notae skill, the input has no pre-existing slides; the
agent must extract a dynamic, timed teaching narrative from static prose.

## Primary use-case

The user almost always wants **one coherent story / plot / theorem-proof-example arc**, not a full paper dump.  
Typical requests:
- “Сделай презентацию по доказательству теоремы X из этой статьи”
- “Возьми только один раздел из этой статьи”
- “Преврати этот кусок лекции в Notae-сценарий”

If the user explicitly asks for the whole document, do it, but still organise it into meaningful scenes rather than one scene per paragraph.

---

## I. Shared Notae rules (identical to the Beamer skill)

### Slide names — mandatory marker comments

Notae names slides itself and keeps the names identical in the terminal,
in warnings and in `media/slides/`:

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


title: {Тема доклада}
author: {…}
…


%--------------- Slide01 ---------------


scene: {Первый слайд}

line q1: {…}
…


%--------------- Slide02 ---------------


scene: {Второй слайд}

…
```

Rules for the marker:
- Begins at column 1, `%` followed by dashes, ` Title ` or ` SlideNN `,
  dashes to the end.
- The name must match what Notae will actually print:
  `Title`, `Slide01`, `Slide02`, … (never `Slide1`, `Slide00`, `Scene_1`,
  `TitleSlide`).
- The number inside `SlideNN` is determined **only** by the order of `scene:`
  blocks — count them as you generate.
- If a scene is added, removed or reordered later, renumber the markers.
- The marker is a comment, so pdflatex ignores it; it does **not** count as
  the “two blank lines after `scene:`” and does **not** replace them.

### Text, formulas, English and diacritics

- A line with ordinary words is text. This is script-independent: Cyrillic,
  English, French, German and accented Latin are treated the same way, no matter
  which babel is declared.
- A line made only of math commands/symbols is a formula.
- Write English prose as plain text, not as `$English sentence$`.
- Explicit math should be marked with `$...$` or `\[...\]`.
- Unicode diacritics (`naïve`, `café`) and LaTeX accents (`na\"ive`, `caf\'e`)
  are both recognised as text.

### Length, margins and density

The presentation margins are **2 cm left and right**; long lines wrap
automatically in both video and PDF, and wrapped lines look bad and trigger a
pre-build warning. Treat density as a hard constraint, not a suggestion.

Notae separates **errors** (LaTeX in used content; they can fail the build)
from **warnings** (wrapping, subtitle length, density). Warnings never fail the
build and do not require a rebuild; only errors are blocking.

**Hard limits (do not exceed without splitting the scene):**

| Metric | Limit |
|---|---|
| Simultaneously visible `line` blocks in one scene | **≤ 7** |
| Physical rows on screen after wrapping (≈90 characters per row at 2 cm margins and 36 pt) | **≤ 10** |
| Subtitle length | **≤ 3 rows** |
| `line` that already wraps to a second physical row | split into two `line`s, or shorten |
| Width of a single formula | must fit ≤ 2/3 of the text area |

**How to estimate.** Before writing a scene, sketch on paper how many physical
rows each `line` takes once it is typeset at size 36 with `align=center` inside
a 2 cm-margined frame. If the total exceeds 10 rows, split the scene. Common
mistakes:

- A chain `A = B = C = D` written as one `line` wraps to 2–3 rows — split it.
- Long `\begin{pmatrix}…\end{pmatrix}` usually needs its own scene.
- A `line` starting with `\textbf{Утверждение.}` plus a formula is almost
  always 2 rows — either put the label on its own `line` (small size) or drop it
  into a `sub`.
- Lists of cases / `\quad`-separated items easily overrun — one item per `line`.

**Subtitle = spoken track.** When it grows past 3 rows, split it into two
`sub`s or move one sentence to the next scene. Do not remove subtitles with
`T: … sub: -`; when the scene ends, the subtitle disappears on its own.

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

% --- user macros transferred from the source ---
% (paste here)

\begin{document}
```

Transfer only packages and macros that are actually used in the extracted
fragment (`amsmath`, `amssymb`, `amsthm`, `mathtools`, `mathrsfs`, `xcolor`,
`tikz` if present, font packages for Cyrillic). Ignore pure bibliography,
hyperref navigation, geometry fine-tuning, etc.

**Guard against macro clashes.** If the source redefines a LaTeX built-in (for
example `\Re`), use `\renewcommand` **after** the package load, and prefer a
distinct name (`\Real`, `\Rdet`) over a silent override. Collisions surface as
`Command \X already defined` in the Notae build log.

### Timing table (seconds)

**Main rule: the average time between actions is 5.0–10.0 seconds.** The delay
is chosen by how complex the **previous** action was — how long the viewer
needs to read it — not by the next action. A short line needs about 5 s; a
complex formula, definition or theorem needs 7–10 s. Intervals of 1–2 s are
reserved only for the very first appearance in a scene.

| Previous action | Delay before the next action |
|---|---|
| First line of a scene (scene just appeared) | 2.0–4.0 |
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

When in doubt, prefer longer delays. A formula that takes the viewer 3 s to
parse should stay on screen for at least that long before the next line, and
the interval after it should be 7–10 s.

### Default styles in `common:`

```latex
common:
line gap: {\vspace{1.0cm}}

style default: size=36 color=TEXT anim=write align=center
style sub default: size=26 color=MUTED
```

### Strict layout rules for scenes (very important)

When the scenario.tex is later compiled with ordinary pdflatex for proof-reading,
correct blank lines make the source readable. Follow these rules **exactly**:

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

Concrete example of a correctly formatted scene:

```latex
%--------------- Slide03 ---------------


scene: {Диофантовы уравнения}


line l1: {а) Решите в целых числах уравнение $21x+76y=0$.}

line l2: {б) Решите в целых числах уравнение $21x+76y=1$.}

line l3: {Сколько решений $(x_0,y_0)$ удовлетворяют условию $0\le x_0\le 75$?}

line l4: {в) В кольце $\mathbb{Z}_{76}$ вычислите $[21]_{76}^{-1}$.}


sub s1: {Линейные уравнения в кольцах $\mathbb{Z}$ и $\mathbb{Z}_{76}$}


T: 2.0 s1

T: 4.0 l1

T: 4.0 l2

T: 4.0 l3

T: 4.0 l4

pause: 8.0


%--------------- Slide04 ---------------
```

- A service word at the beginning of a line ends `{…}` only if a closing `}`
  already stands before it (spaces, blank lines and an optional `\\` after the
  `}` do not matter). Close the content before `T:`, `line:`, `scene:`, etc.
- Allowed formatting for readability: `line l1: {Текст}\\` followed by
  `T: 0.5 l1`.
- Service-word-like lines can be shown as literal text only while the `{…}` is
  still open; if it is never closed, Notae reports a clear error.
- If the content itself ends with `}`, write **two** closing braces (`…}}`, or
  `…\}}` when the literal brace is escaped); otherwise the last `}` is treated
  as the content delimiter.
- Colour only for genuine emphasis (“проверьте!”, key remarks).

---

## II. Workflow (algorithmic, follow in order)

### Step 1. Pick the narrative arc

Read the source. Decide what **one** story to tell:

1. theorem + proof,
2. definition + examples + consequences,
3. computational algorithm with steps,
4. historical/conceptual development,
5. problem + solution.

If the user named a section / theorem / topic — stay strictly inside it.
If not — pick the most self-contained and interesting arc and state the choice
briefly. Write that one-line justification in the chat, not in the file.

### Step 2. Sketch the scene list on paper

Do **not** start writing `scenario.tex` yet. List scenes as short titles:

```
Title
Slide01. Motivation
Slide02. Definition of the object
Slide03. Auxiliary fact / lemma
Slide04. Idea of proof
Slide05. Step 1 of proof
Slide06. Step 2 of proof
Slide07. Conclusion / consequence
Slide08. Thanks
```

Assign each sketch a **density budget** (how many `line`s, how many `sub`s),
using the hard limits above. If any sketch would need > 7 visible `line`s, split
it now — retrofitting a split later almost always breaks the timing.

### Step 3. Decide visible content per scene

For each scene, list the exact mathematical statements that must be visible,
almost verbatim from the source. Move the “why”/“comment” prose into subtitles.
Displayed formulas become individual `line`s. Lists become one `line` per item
(never a single `enumerate`). If you see a formula that will wrap, split it:
`A = B` on one `line`, `= C` on the next.

### Step 4. Write the spoken track

Compose subtitles in the voice of a lecturer, not a copy of the text:

- “Сейчас мы увидим, зачем нужна равномерная непрерывность”,
- “Ключевой момент — оценка дисперсии”,
- “Проверьте сами, что дисперсия действительно равна …”.

Place each subtitle early in the scene or right before a hard step. Keep each
subtitle ≤ 3 rows.

### Step 5. Compose the file

Emit in this order:

1. preamble (packages actually used + macros transferred from the source),
2. `\begin{document}`,
3. `common:` block with default styles,
4. `Title` marker + title block if any field is meaningful,
5. for each scene: marker comment (`%------ SlideNN ------`) →
   `scene:` → lines → subs → timeline → final pause,
6. final “Спасибо” scene if appropriate,
7. `\end{document}`.

### Step 6. Pre-output self-check (block release until it passes)

Before printing the file, run this checklist and **fix everything that fails**:

| # | Check | Pass criterion |
|---|---|---|
| 1 | Marker comments | `%------ Title ------` before the title block (if any) and `%------ SlideNN ------` before each scene, numbered consecutively from 1 |
| 2 | Density | every scene ≤ 7 visible `line`s and ≤ 10 physical rows estimated |
| 3 | Wrapping | no `line` that will visibly wrap; long formulas split |
| 4 | Subtitle | every `sub` ≤ 3 rows |
| 5 | No `T: … sub: -` | sub-titles never explicitly removed |
| 6 | Balancing | every `{…}` closed before the next service word |
| 7 | Escape | every formula is inside `$…$` / `\[…\]`; English prose not wrapped in `$` |
| 8 | Macro clashes | any `\renewcommand` that overrides a built-in is justified, otherwise rename |
| 9 | Diacritics | LaTeX accents (`caf\'{e}`), not raw Unicode combining chars in code |
| 10 | Timing | mean delay between actions 5.0–10.0 s; first line ≥ 2.0 s; complex/theorem ≥ 7.0 s; final pause ≥ 8.0 s |
| 11 | Blank-line layout | rules 1–8 from the “Strict layout” section hold for every scene |
| 12 | Story coherence | every scene has a stated pedagogical purpose from Step 2 |

Only after all 12 pass, return the file.

---

## III. Fragments (non-ideal, for reference)

These fragments illustrate the mechanics of conversion. They are **not** a
model course, a typical talk, or a template to copy verbatim: always adapt the
topics to the user's own material. The intervals are illustrative; keep the
mean delay at 5–10 s as described in the timing table.

### Example A. Extracting one theorem

Source fragment:

> Теорема (Вейерштрасс). Для любой непрерывной функции $f$ на отрезке
> существует последовательность многочленов, равномерно сходящаяся к $f$.
> Доказательство мы проведём с помощью многочленов Бернштейна…

Becomes:

```latex
%--------------- Slide05 ---------------


scene: {Теорема Вейерштрасса}


line l1: {\textbf{Теорема} (Вейерштрасс, 1885).}

line l2: {Для любой $f \in C[a,b]$ и любого $\varepsilon>0$}

line l3: {существует многочлен $P$ такой, что}

line l4: {$\|f - P\|_{C[a,b]} < \varepsilon.$}


sub s1: {Формулировка дана для произвольного отрезка. Дальше работаем на $[0,1]$.}


T: 8.0 l1

T: 3.0 l2

T: 2.0 l3

T: 5.0 l4

T: 3.0 s1

pause: 8.0
```

### Example B. Density fix — split, not squeeze

Bad (7 `line`s with wrapped formulas, ~14 physical rows):

```latex
line c1: {$\Det(A) = \sum_{\sigma\in S_n} (-1)^{\sgn(\sigma)} \prod_{\text{циклы } \sigma} \Re(a_{i_1 i_2}\cdots a_{i_k i_1}).$}

line c2: {Здесь $\Re(q)$ — вещественная часть, а произведение берётся по всем циклам перестановки, что требует доказательства независимости от порядка.}
…
```

Good (split over two scenes, each ≤ 7 rows):

```latex
%--------------- Slide11 ---------------


scene: {Комбинаторное определение}


line c1: {Для произвольной $A\in M_n(\HH)$:}

line c2: {$\Det(A) = \sum\limits_{\sigma\in S_n} (-1)^{\sgn(\sigma)} \prod\limits_{\text{циклы } \sigma} \Re\bigl(a_{i_1 i_2}\cdots a_{i_k i_1}\bigr).$}

line c3: {$\Re(q)$ — вещественная часть кватерниона.}


sub s1: {Формула задаёт определитель для любой кватернионной матрицы.}


T: 2.0 c1

T: 4.0 c2

T: 4.0 c3

T: 4.0 s1

pause: 10.0


%--------------- Slide12 ---------------


scene: {Независимость от порядка циклов}


line k1: {\textbf{Утверждение.} Результат не зависит от порядка циклов.}

line k2: {\textbf{Доказательство.} Каждый цикл даёт вещественное число.}

line k3: {Произведение вещественных чисел коммутативно.}

line k4: {Следовательно, порядок не влияет.}


sub s1: {Некоммутативность исходных кватернионов снимается переходом к $\Re$.}


T: 2.0 k1

T: 4.0 k2

T: 4.0 k3

T: 4.0 k4

T: 4.0 s1

pause: 10.0
```

### Example C. List of definitions

Instead of one big block — one `line` per item, separate delays:

```latex
line l1: {$(m,n)$ --- наибольший общий делитель}

line l2: {$n\ \vdots\ d$ --- $n$ делится на $d$}

line l3: {$\mathbb{Z}_n$ --- кольцо вычетов по модулю $n$}
```

### Example D. Long source, unclear scope

If the user gave a whole chapter and no plot — pick one bright arc (usually
the main theorem of the section) and say briefly:

> «Извлёк сюжет “доказательство теоремы X”; остальные разделы оставил за
> кадром.»

---

## Output

Always produce a complete, self-contained `scenario.tex`.
Do not emit Python or Manim code.
If the source is long, prefer a focused narrative over completeness.
Every scene must carry its `%------ SlideNN ------` marker; the file
must pass the Step 6 self-check before it is returned.
