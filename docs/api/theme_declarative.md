<!-- handauthored: do not regenerate -->
# slappyengine.ui.theme.declarative — API Reference

## Declarative Theme Grammar

> Hand-written reference for the **HTML5-like declarative theme spec**:
> an ergonomic, CSS-inspired source format that compiles into the
> existing `ThemeSpec` runtime. For the underlying dataclasses see
> [`ui_theme.md`](ui_theme.md); for the editor shell that hosts the
> Import Theme dialog see [`ui_editor.md`](ui_editor.md).

The declarative spec exists so that end users, content authors, and
mod-community contributors can write a theme without having to touch a
Python file. A `.theme.css` file parses through
`DeclarativeTheme.parse_file()` into the same `ThemeSpec` instance that
the built-in themes ship as, and the parse result registers with the
theme registry through `load_declarative()` for the editor's Theme
Switcher to pick up.

## Public surface

```python
from slappyengine.ui.theme import (
    DeclarativeTheme, DeclarativeThemeError, NAMED_COLORS, load_declarative,
)

# 1. Parse a string (in-memory theme authoring).
theme = DeclarativeTheme.parse(source)

# 2. Parse a file from disk.
theme = DeclarativeTheme.parse_file(Path("themes/my_theme.theme.css"))

# 3. Round-trip: theme -> declarative source string.
source = DeclarativeTheme.dump(theme)

# 4. Editor "File -> Import Theme" one-shot: parses + registers + returns name.
name = load_declarative(Path("themes/my_theme.theme.css"))
```

Everything is pure Python — the parser has **no external dependencies**.
The tokenizer + recursive-descent parser weigh in under 700 lines of
straight-line code so IDE authors can trace any error back to a specific
grammar production.

## Grammar overview

```
theme       := '@theme' STRING '{' section* '}'
section     := IDENT ('.' IDENT)? '{' (entry | list_entry)* '}'
entry       := key ':' value ';'
list_entry  := IDENT (',' IDENT)* ';'          ; e.g. creatures { fox, bee; }
key         := IDENT                            ; may contain hyphens
value       := token+                           ; whitespace-separated
                                                  scalar / compound
```

**Whitespace** is insignificant (except inside quoted strings). Comments
follow C: `// line` and `/* block */`. Case sensitivity: identifiers
and keywords are compared verbatim; named colours are matched
case-insensitively.

### Colours

| Form              | Example              | Notes                                     |
|-------------------|----------------------|-------------------------------------------|
| `#RGB`            | `#F0A`               | Each nibble is duplicated, alpha = 1.     |
| `#RRGGBB`         | `#FF6FB5`            | Alpha = 1.                                |
| `#RRGGBBAA`       | `#FF6FB580`          | Alpha as `AA / 255`.                      |
| `rgba(r,g,b,a)`   | `rgba(255, 111, 181, 0.3)` | Comma-separated, alpha in `[0, 1]`. |
| Named             | `bubblegum-pink`     | See `NAMED_COLORS` below.                 |

### Named colours

The built-in dictionary carries the palette of the diary / notebook /
scrapbook families that ship with the engine. Non-exhaustive:

```
pastel-pink, bubblegum-pink, dusty-rose, cherry-blossom,
cream, parchment, caramel, sage, ink, leather, sepia,
sunflower, lavender, mint, peach, seafoam,
white, black, transparent, red, green, blue
```

The full list lives in `slappyengine.ui.theme.NAMED_COLORS`. Unknown
names raise `DeclarativeThemeError` at parse time with a line/column.

### Sizes

Numeric values accept the suffixes `px`, `em`, `pt`; the suffix is
stripped and the numeric part becomes a plain float. The unit is
advisory — the runtime treats every size as DPG pixels.

### Compound values

Space-separated tokens on the right-hand side of `:` collapse into a
Python list at parse time. Two common shapes:

* `padding: 10px 8px;` → `padding_x=10, padding_y=8`
* `padding: 10px 8px 12px 6px;` → CSS-style (top, right, bottom, left);
  we take the *right* as `padding_x` and the *top* as `padding_y`.
* `shadow: 4px 0px rgba(255, 111, 181, 0.3);` → the max numeric goes to
  `shadow_size`, the RGBA to `shadow_color`.

### Sections

| Section                   | Maps to                                       |
|---------------------------|-----------------------------------------------|
| `palette`                 | `ThemeSpec.palette` (dict of `Color`)         |
| `fonts`                   | `ThemeSpec.fonts` (dict of `Font`)            |
| `frames.<kind>`           | `ThemeSpec.frames.<kind>` (`FrameStyle`)      |
| `panels.<kind>`           | Metadata under `panel.<kind>.<key>`           |
| `shader.<slot>`           | `ThemeSpec.background_shader` when slot is `background` |
| `creatures` (list-style)  | `metadata["creature_roster"]`                 |
| `stickers` (list-style)   | `metadata["sticker_roster"]`                  |
| `dividers` (list-style)   | `metadata["divider_roster"]`                  |

### Python interpolation — `${...}`

Any value fragment can hold `${expr}` blocks; each is evaluated through
`slappyengine.math.evaluate` (the sandbox-locked eval used across the
engine — see [`math.md`](math.md)). The sandbox exposes stdlib `math`
symbols plus a small builtins bag; anything else (imports, `open`,
attribute access, dunders) raises. Quoted-string payloads pass through
verbatim so an interpolated hex works:

```
palette {
    primary: rgba(${100 + 55}, ${10 * 2}, 50, ${1.0 / 2});
    accent:  ${"#AABBCC"};
}
```

### Error handling

Every parse-time failure raises `DeclarativeThemeError` (subclass of
`ValueError`). The exception carries `.line` / `.column` and prefixes
the message with `line L col C:` so editor consumers can jump to the
faulty token.

## Round-trip

`DeclarativeTheme.dump(theme)` walks a `ThemeSpec` back out into a
declarative string. The result re-parses to a `ThemeSpec` with the same
palette, fonts, frames, background shader, and roster metadata. Note:
the *semantic tokens* are recomputed from the palette on re-parse — the
declarative surface treats semantic tokens as *derived*, not authored.
If a theme needs custom semantic tokens beyond palette-derived
defaults, keep the theme in Python and export a snapshot with `dump`
purely for archival / diffing purposes.

## Editor integration — File → Import Theme

The editor's File menu carries an **Import Theme…** entry that opens a
file picker filtered to `.theme.css`. On selection:

1. `load_declarative(path)` parses the file and registers the result.
2. The Theme Switcher panel refreshes its list.
3. `apply_theme(name)` is called on the freshly-parsed theme.

A parsed-marker file is written into
`~/.slappyengine/themes/<name>.cache.json` so subsequent editor launches
can pre-populate the "Recently Imported" section. The cache is advisory
— parsing is fast enough (< 1 ms for a typical 100-line theme) that the
cache is diagnostic rather than a speed-critical path.

## Example 1 — minimal theme

```css
@theme "my_first_theme" {
    palette {
        primary: #FF6FB5;
    }
}
```

Every other section is optional. The palette-only theme picks
neutral-grey defaults for missing semantic-token roles so the editor
still renders correctly.

## Example 2 — cozy notebook (matches `COZY_DIARY` variant)

```css
@theme "my_cozy_theme" {
    palette {
        primary: #FF6FB5;
        secondary: #E7DDF1;
        background: #FBF7EC;
        surface: #F5EDDD;
        ink: #1F2F66;
        border: rgba(124, 85, 50, 0.9);
    }
    fonts {
        header: "Caveat", 20;
        body: "Quicksand", 14;
        code: "Fira Code", 12;
    }
    frames.default {
        border-size: 2px;
        rounding: 12px;
        padding: 10px 8px;
        shadow: 4px 0px rgba(255, 111, 181, 0.3);
    }
    frames.toolbar {
        border-size: 1px;
        rounding: 6px;
        padding: 6px 4px;
    }
    panels.sidebar {
        background: #FBF7EC;
        border: 1px solid #E7DDF1;
    }
    shader.background {
        kind: "ruled_paper";
        line-color: #A7E7C7;
    }
    creatures {
        fox_01, butterfly_01, red_panda_02;
    }
    stickers {
        heart, star, flower;
    }
}
```

## Example 3 — formula-driven palette

```css
@theme "sunset_generated" {
    // Palette entries derived from a shared "warmth" scalar so tweaking
    // one number re-tones the entire theme.
    palette {
        primary:    rgba(${200 + 40}, ${120 + 20}, ${80  - 10}, 1);
        secondary:  rgba(${200 + 20}, ${100 + 30}, ${60  - 20}, 1);
        background: rgba(${240},      ${230},      ${220},      1);
        ink:        rgba(${40},       ${30},       ${25},       1);
    }
    fonts {
        header: "Caveat", 22;
        body:   "Quicksand", 14;
    }
    frames.default {
        border-size: ${1 + 1}px;
        rounding: ${8 * 1.5}px;
        padding: 12px 10px;
    }
    shader.background {
        kind: "watercolor_wash";
    }
}
```

Because the interpolated fragments are pure expressions, keeping every
palette entry aligned to a single tweakable "temperature" is just a
matter of authoring the arithmetic. No preprocessor, no shell-outs —
the sandbox lives inside the parser.

## Full API summary

```python
class DeclarativeTheme:
    @classmethod
    def parse(cls, source: str) -> ThemeSpec: ...
    @classmethod
    def parse_file(cls, path: str | Path) -> ThemeSpec: ...
    @classmethod
    def dump(cls, theme: ThemeSpec) -> str: ...


class DeclarativeThemeError(ValueError):
    line: int | None
    column: int | None


NAMED_COLORS: dict[str, tuple[int, int, int, float]]


def load_declarative(path: str | Path) -> str:
    """Parse, register, cache-marker, return theme name."""
```

## Design notes

The grammar deliberately mirrors CSS in the *shape* of a section but
diverges wherever a CSS token would create parse ambiguity. Specifically:

* **Braces + semicolons are mandatory** — no significant indentation,
  no bare property lists.
* **Dotted section names** carry the sub-section
  (`frames.default` → `PanelFrameSet.default`) rather than reusing CSS's
  compound-selector convention.
* **`@theme "name"`** is the sole top-level directive so a fresh reader
  never has to guess which block is authoritative.

The parser refuses attribute access, subscripting, and dunder names in
interpolation payloads by delegating to `slappyengine.math.evaluate`,
which walks the AST in `_ensure_safe_ast`. That's the same sandbox the
formula-editor uses across the engine, so declarative themes inherit
every hardening improvement the sandbox picks up over time.
