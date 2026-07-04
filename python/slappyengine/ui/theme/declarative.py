"""Declarative "HTML5-like" theme spec parser.

A hand-rolled recursive-descent parser + emitter that lets end users
customize SlapPyEngine themes with a CSS-inspired grammar which compiles
into the existing :class:`~slappyengine.ui.theme.theme_spec.ThemeSpec`
runtime.

Design goals
------------
* **Zero external dependencies.**  Pure Python parser (a hand-written
  tokenizer + recursive-descent grammar) — no ``ply`` / ``lark`` / etc.
* **Faithful line numbers.**  Errors raise :class:`DeclarativeThemeError`
  with the offending token's line + column so notebook-style editors
  can jump-to.
* **Round-trippable.**  :meth:`DeclarativeTheme.dump` produces a source
  string that re-parses through :meth:`DeclarativeTheme.parse` to an
  equivalent :class:`ThemeSpec`.
* **Python-interpolation.**  Values may embed ``${expr}`` fragments.
  Each fragment is fed to :func:`slappyengine.math.evaluate` (sandboxed
  eval) so declarative themes can pull palette colours from a formula
  without giving away the keys to the interpreter.
* **Cache-friendly.**  :func:`load_declarative` writes a parsed marker
  into ``~/.slappyengine/themes/`` so repeat launches skip the parse
  cost — the on-disk cache is purely advisory (parses stay fast).

Grammar
-------
::

    theme       := '@theme' STRING '{' section* '}'
    section     := IDENT ('.' IDENT)? '{' entry* '}'
    entry       := key ':' value ';'
                 | IDENT (',' IDENT)* ';'     ; creature list-style
    key         := IDENT ('-' IDENT)*
    value       := token+                     ; whitespace-separated tokens
                                                grouped up to the ';'

Colours accept ``#RGB``, ``#RRGGBB``, ``#RRGGBBAA``, ``rgba(r,g,b,a)``
or a named colour drawn from the built-in dictionary
(``pastel-pink``, ``bubblegum-pink``, …). Sizes use the ``Npx`` /
``Nem`` / ``Npt`` suffixes with ``px`` treated as the canonical unit.

See ``docs/api/theme_declarative.md`` for the tutorial-level reference.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .theme_spec import (
    Color,
    Font,
    FrameStyle,
    Gradient,
    PanelFrameSet,
    SemanticTokens,
    ShaderEffect,
    ThemeSpec,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DeclarativeThemeError(ValueError):
    """Raised for any parse-time or emit-time error.

    Carries an optional ``line`` / ``column`` so notebook-style editors
    can jump to the offending source location. Message layout is
    ``"line L col C: reason"`` when both are present.
    """

    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
    ) -> None:
        self.line = line
        self.column = column
        if line is not None and column is not None:
            super().__init__(f"line {line} col {column}: {message}")
        elif line is not None:
            super().__init__(f"line {line}: {message}")
        else:
            super().__init__(message)


# ---------------------------------------------------------------------------
# Named colour dictionary
# ---------------------------------------------------------------------------
#
# Kept small on purpose — the intent is to cover the colours the diary /
# notebook family actually reference (see ``docs/theme_diary_family_*``).
# Users can always fall back to explicit ``#RRGGBB`` for anything else.


NAMED_COLORS: dict[str, tuple[int, int, int, float]] = {
    # Notebook / kawaii pinks + roses.
    "pastel-pink": (255, 192, 203, 1.0),
    "bubblegum-pink": (255, 111, 181, 1.0),
    "dusty-rose": (216, 162, 168, 1.0),
    "cherry-blossom": (255, 183, 197, 1.0),
    # Diary tones.
    "cream": (245, 237, 221, 1.0),
    "parchment": (241, 228, 197, 1.0),
    "caramel": (176, 122, 92, 1.0),
    "sage": (141, 167, 124, 1.0),
    "ink": (46, 41, 38, 1.0),
    "leather": (124, 85, 50, 1.0),
    "sepia": (92, 70, 48, 1.0),
    # Scrapbook / cottagecore.
    "sunflower": (255, 214, 92, 1.0),
    "lavender": (200, 180, 232, 1.0),
    "mint": (183, 232, 210, 1.0),
    "peach": (255, 199, 168, 1.0),
    "seafoam": (159, 226, 191, 1.0),
    # Structural neutrals.
    "white": (255, 255, 255, 1.0),
    "black": (0, 0, 0, 1.0),
    "transparent": (0, 0, 0, 0.0),
    # Convenience CSS-adjacent aliases.
    "red": (255, 0, 0, 1.0),
    "green": (0, 128, 0, 1.0),
    "blue": (0, 0, 255, 1.0),
}


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


@dataclass
class _Token:
    kind: str
    value: str
    line: int
    column: int


_IDENT_START = re.compile(r"[A-Za-z_]")
_IDENT_CONT = re.compile(r"[A-Za-z0-9_\-]")


def _tokenize(source: str) -> list[_Token]:
    """Return the tokens of *source*.

    Kinds:

    * ``AT_THEME``   — the ``@theme`` keyword
    * ``LBRACE`` / ``RBRACE`` — ``{`` / ``}``
    * ``LPAREN`` / ``RPAREN`` — ``(`` / ``)``
    * ``COMMA`` / ``COLON`` / ``SEMI`` / ``DOT``
    * ``STRING``     — quoted (single or double)
    * ``INTERP``     — ``${...}`` verbatim payload
    * ``HEX``        — ``#RGB`` / ``#RRGGBB`` / ``#RRGGBBAA``
    * ``NUMBER``     — integer or float, incl. optional ``px`` / ``em`` / ``pt``
    * ``IDENT``      — bare identifier (including internal hyphens)
    """
    tokens: list[_Token] = []
    i = 0
    line = 1
    col = 1
    n = len(source)
    while i < n:
        c = source[i]
        # Whitespace ------------------------------------------------------
        if c == "\n":
            line += 1
            col = 1
            i += 1
            continue
        if c in " \t\r":
            col += 1
            i += 1
            continue
        # Comments (// line, /* block */) ---------------------------------
        if c == "/" and i + 1 < n and source[i + 1] == "/":
            j = source.find("\n", i)
            if j == -1:
                i = n
            else:
                i = j
            continue
        if c == "/" and i + 1 < n and source[i + 1] == "*":
            j = source.find("*/", i + 2)
            if j == -1:
                raise DeclarativeThemeError(
                    "unterminated /* ... */ comment", line=line, column=col
                )
            # Track newlines inside the block.
            block = source[i:j + 2]
            line += block.count("\n")
            # Column: after a multi-line comment, col resets to the char
            # after the last newline in the block.
            last_nl = block.rfind("\n")
            if last_nl == -1:
                col += len(block)
            else:
                col = len(block) - last_nl
            i = j + 2
            continue
        # Punctuation -----------------------------------------------------
        punct = {
            "{": "LBRACE",
            "}": "RBRACE",
            "(": "LPAREN",
            ")": "RPAREN",
            ",": "COMMA",
            ":": "COLON",
            ";": "SEMI",
            ".": "DOT",
        }
        if c in punct:
            tokens.append(_Token(punct[c], c, line, col))
            i += 1
            col += 1
            continue
        # Strings ---------------------------------------------------------
        if c == '"' or c == "'":
            quote = c
            start_col = col
            j = i + 1
            buf: list[str] = []
            while j < n and source[j] != quote:
                if source[j] == "\\" and j + 1 < n:
                    esc = source[j + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r",
                                "\\": "\\", '"': '"', "'": "'"}.get(esc, esc))
                    j += 2
                    col += 2
                    continue
                if source[j] == "\n":
                    line += 1
                    col = 1
                else:
                    col += 1
                buf.append(source[j])
                j += 1
            if j >= n:
                raise DeclarativeThemeError(
                    f"unterminated string starting with {quote}",
                    line=line, column=start_col,
                )
            tokens.append(_Token("STRING", "".join(buf), line, start_col))
            i = j + 1
            col += 1
            continue
        # Interpolation ${...} -------------------------------------------
        if c == "$" and i + 1 < n and source[i + 1] == "{":
            start_col = col
            depth = 1
            j = i + 2
            buf = []
            while j < n and depth > 0:
                if source[j] == "{":
                    depth += 1
                elif source[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                buf.append(source[j])
                if source[j] == "\n":
                    line += 1
                    col = 1
                else:
                    col += 1
                j += 1
            if j >= n:
                raise DeclarativeThemeError(
                    "unterminated ${...} interpolation",
                    line=line, column=start_col,
                )
            tokens.append(_Token("INTERP", "".join(buf).strip(),
                                 line, start_col))
            i = j + 1
            col += 1
            continue
        # Hex colour ------------------------------------------------------
        if c == "#":
            start_col = col
            j = i + 1
            while j < n and re.match(r"[0-9A-Fa-f]", source[j]):
                j += 1
            tokens.append(_Token("HEX", source[i:j], line, start_col))
            col += j - i
            i = j
            continue
        # Numbers ---------------------------------------------------------
        if c.isdigit() or (c == "-" and i + 1 < n and source[i + 1].isdigit()) \
                or (c == "." and i + 1 < n and source[i + 1].isdigit()):
            start_col = col
            j = i
            if source[j] == "-":
                j += 1
            while j < n and (source[j].isdigit() or source[j] == "."):
                j += 1
            # Optional unit suffix.
            unit_start = j
            while j < n and source[j].isalpha():
                j += 1
            raw = source[i:j]
            tokens.append(_Token("NUMBER", raw, line, start_col))
            col += j - i
            i = j
            # ``unit_start`` reserved for future validation (currently
            # embedded verbatim in the token's value).
            _ = unit_start
            continue
        # ``@theme`` keyword ---------------------------------------------
        if c == "@":
            start_col = col
            j = i + 1
            while j < n and _IDENT_CONT.match(source[j]):
                j += 1
            keyword = source[i:j]
            if keyword == "@theme":
                tokens.append(_Token("AT_THEME", keyword, line, start_col))
            else:
                raise DeclarativeThemeError(
                    f"unknown directive {keyword!r}",
                    line=line, column=start_col,
                )
            col += j - i
            i = j
            continue
        # Identifiers -----------------------------------------------------
        if _IDENT_START.match(c):
            start_col = col
            j = i + 1
            while j < n and _IDENT_CONT.match(source[j]):
                j += 1
            tokens.append(_Token("IDENT", source[i:j], line, start_col))
            col += j - i
            i = j
            continue
        raise DeclarativeThemeError(
            f"unexpected character {c!r}", line=line, column=col
        )
    tokens.append(_Token("EOF", "", line, col))
    return tokens


# ---------------------------------------------------------------------------
# Value evaluation helpers
# ---------------------------------------------------------------------------


def _evaluate_interpolation(payload: str) -> Any:
    """Evaluate a ``${...}`` payload through the math sandbox.

    Colour-shaped strings — ``'#RRGGBB'``, ``'rgba(...)'``, or a named
    colour — pass through *before* the sandbox so palette authors can
    return a hex literal from their expression without the sandbox
    rejecting the string.
    """
    stripped = payload.strip()
    # Quoted literal colour → parse directly, keep the string.
    for quote in ("'", '"'):
        if stripped.startswith(quote) and stripped.endswith(quote):
            return stripped[1:-1]
    # Actual expression → sandbox.
    from slappyengine.math import evaluate as _sandbox_evaluate
    try:
        return _sandbox_evaluate(stripped)
    except Exception as exc:  # noqa: BLE001 - re-raise as declarative error
        raise DeclarativeThemeError(
            f"interpolation {payload!r} failed: {exc}"
        ) from exc


def _parse_hex_color(hex_str: str, *, line: int | None = None) -> Color:
    """Parse ``#RGB`` / ``#RRGGBB`` / ``#RRGGBBAA`` into a :class:`Color`."""
    if not hex_str.startswith("#"):
        raise DeclarativeThemeError(
            f"hex colour must start with '#'; got {hex_str!r}", line=line
        )
    body = hex_str[1:]
    if len(body) == 3:
        r, g, b = (int(ch * 2, 16) for ch in body)
        return Color(r=r, g=g, b=b, a=1.0)
    if len(body) == 6:
        r = int(body[0:2], 16)
        g = int(body[2:4], 16)
        b = int(body[4:6], 16)
        return Color(r=r, g=g, b=b, a=1.0)
    if len(body) == 8:
        r = int(body[0:2], 16)
        g = int(body[2:4], 16)
        b = int(body[4:6], 16)
        a = int(body[6:8], 16) / 255.0
        return Color(r=r, g=g, b=b, a=a)
    raise DeclarativeThemeError(
        f"hex colour {hex_str!r} must be 3, 6, or 8 hex digits", line=line
    )


def _resolve_named_color(name: str, *, line: int | None = None) -> Color:
    key = name.lower()
    if key not in NAMED_COLORS:
        raise DeclarativeThemeError(
            f"unknown named colour {name!r}", line=line
        )
    r, g, b, a = NAMED_COLORS[key]
    return Color(r=r, g=g, b=b, a=a)


def _to_color(value: Any, *, line: int | None = None) -> Color:
    """Coerce a parsed value into a :class:`Color`."""
    if isinstance(value, Color):
        return value
    if isinstance(value, str):
        v = value.strip()
        if v.startswith("#"):
            return _parse_hex_color(v, line=line)
        return _resolve_named_color(v, line=line)
    if isinstance(value, (list, tuple)) and len(value) == 4:
        r, g, b, a = value
        return Color(r=int(r), g=int(g), b=int(b), a=float(a))
    raise DeclarativeThemeError(
        f"cannot coerce {value!r} to a Color", line=line
    )


def _parse_number_token(raw: str, *, line: int | None = None) -> float:
    """Strip any unit suffix from a NUMBER token and return the float."""
    m = re.match(r"^(-?\d+(?:\.\d+)?|\.\d+)([A-Za-z]*)$", raw)
    if not m:
        raise DeclarativeThemeError(
            f"malformed number {raw!r}", line=line
        )
    return float(m.group(1))


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


class _Parser:
    """Hand-written recursive-descent parser over the token stream."""

    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._pos = 0

    # --- token stream helpers --------------------------------------------

    def _peek(self, offset: int = 0) -> _Token:
        return self._tokens[min(self._pos + offset, len(self._tokens) - 1)]

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        if self._pos < len(self._tokens) - 1:
            self._pos += 1
        return tok

    def _expect(self, kind: str, *, message: str | None = None) -> _Token:
        tok = self._peek()
        if tok.kind != kind:
            expected = message or f"expected {kind}"
            raise DeclarativeThemeError(
                f"{expected}; got {tok.kind} {tok.value!r}",
                line=tok.line, column=tok.column,
            )
        return self._advance()

    # --- top level -------------------------------------------------------

    def parse(self) -> ThemeSpec:
        self._expect("AT_THEME", message="expected '@theme' at start of file")
        name_tok = self._expect("STRING", message="expected quoted theme name")
        self._expect("LBRACE", message="expected '{' after theme name")

        sections: dict[str, dict[str, Any]] = {}
        sub_sections: dict[str, dict[str, dict[str, Any]]] = {}
        list_sections: dict[str, list[str]] = {}

        while self._peek().kind != "RBRACE":
            if self._peek().kind == "EOF":
                raise DeclarativeThemeError(
                    "unexpected end of file inside '@theme' block",
                    line=self._peek().line, column=self._peek().column,
                )
            self._parse_section(sections, sub_sections, list_sections)
        self._expect("RBRACE", message="expected '}' to close '@theme' block")

        return self._compose_theme(
            name=name_tok.value,
            sections=sections,
            sub_sections=sub_sections,
            list_sections=list_sections,
        )

    # --- section dispatch -------------------------------------------------

    def _parse_section(
        self,
        sections: dict[str, dict[str, Any]],
        sub_sections: dict[str, dict[str, dict[str, Any]]],
        list_sections: dict[str, list[str]],
    ) -> None:
        head_tok = self._expect(
            "IDENT", message="expected section name identifier"
        )
        head = head_tok.value
        sub: str | None = None
        if self._peek().kind == "DOT":
            self._advance()
            sub_tok = self._expect(
                "IDENT", message="expected sub-section name after '.'"
            )
            sub = sub_tok.value
        self._expect("LBRACE", message=f"expected '{{' after section {head!r}")

        # Two body shapes:
        #   - key: value; key: value;  (map)
        #   - ident, ident, ident;     (list, e.g. `creatures { fox, bee; }`)
        # We commit to a shape after peeking the first non-brace token.
        # If we see IDENT followed by ',' or ';' → list. Otherwise → map.
        body_kind = self._peek_body_kind(head_tok)

        if body_kind == "list":
            names = self._parse_ident_list()
            list_sections.setdefault(head, []).extend(names)
        else:
            entries = self._parse_entry_block()
            if sub is None:
                sections.setdefault(head, {}).update(entries)
            else:
                sub_sections.setdefault(head, {})[sub] = entries
        self._expect("RBRACE", message="expected '}' to close section")

    def _peek_body_kind(self, head: _Token) -> str:
        # Empty block → map (no ambiguity).
        first = self._peek()
        if first.kind == "RBRACE":
            return "map"
        # First token is an IDENT and the *second* token is COMMA or SEMI
        # → list style.
        if first.kind == "IDENT":
            second = self._peek(1)
            if second.kind in ("COMMA", "SEMI"):
                return "list"
        return "map"

    def _parse_ident_list(self) -> list[str]:
        names: list[str] = []
        while True:
            tok = self._expect(
                "IDENT", message="expected identifier in list-style section"
            )
            names.append(tok.value)
            if self._peek().kind == "COMMA":
                self._advance()
                continue
            self._expect("SEMI", message="expected ';' after list")
            # Multiple ';'-terminated lists inside one block are legal.
            if self._peek().kind == "RBRACE":
                break
            if self._peek().kind == "IDENT":
                continue
            break
        return names

    def _parse_entry_block(self) -> dict[str, Any]:
        entries: dict[str, Any] = {}
        while self._peek().kind != "RBRACE":
            if self._peek().kind == "EOF":
                raise DeclarativeThemeError(
                    "unexpected end of file inside section body",
                    line=self._peek().line, column=self._peek().column,
                )
            key = self._parse_key()
            self._expect("COLON", message=f"expected ':' after key {key!r}")
            value = self._parse_value_until_semi()
            self._expect("SEMI", message=f"expected ';' after value for {key!r}")
            entries[key] = value
        return entries

    def _parse_key(self) -> str:
        parts = [self._expect("IDENT", message="expected key identifier").value]
        # Allow ``foo-bar`` where the tokenizer merged the hyphen, but also
        # ``foo`` ``-`` ``bar`` (defensive; tokenizer keeps the dash).
        return "-".join(parts)

    # --- value token bag -------------------------------------------------

    def _parse_value_until_semi(self) -> Any:
        """Consume tokens up to the next ';' at brace-depth 0.

        Returns:
        * A single scalar (Color, float, int, str) when only one token
          appears.
        * A ``list`` of scalars for compound values (``10px 8px``,
          ``4px 2px rgba(...)``).
        """
        parts: list[Any] = []
        while True:
            tok = self._peek()
            if tok.kind == "SEMI":
                break
            if tok.kind == "EOF":
                raise DeclarativeThemeError(
                    "unexpected end of file inside value",
                    line=tok.line, column=tok.column,
                )
            parts.append(self._parse_value_token())
            # Allow (optional) commas between value tokens for e.g.
            # ``fonts { header: "Caveat", 20; }`` — the comma is purely
            # cosmetic here.
            if self._peek().kind == "COMMA":
                self._advance()
        if len(parts) == 1:
            return parts[0]
        return parts

    def _read_rgba_component(self) -> float:
        """Read a NUMBER or ${...} expression as an rgba() component."""
        tok = self._peek()
        if tok.kind == "NUMBER":
            self._advance()
            return _parse_number_token(tok.value, line=tok.line)
        if tok.kind == "INTERP":
            self._advance()
            return float(_evaluate_interpolation(tok.value))
        raise DeclarativeThemeError(
            f"expected number or ${{...}} in rgba(); got {tok.kind}",
            line=tok.line, column=tok.column,
        )

    def _parse_value_token(self) -> Any:
        tok = self._peek()
        if tok.kind == "HEX":
            self._advance()
            return _parse_hex_color(tok.value, line=tok.line)
        if tok.kind == "NUMBER":
            self._advance()
            return _parse_number_token(tok.value, line=tok.line)
        if tok.kind == "STRING":
            self._advance()
            return tok.value
        if tok.kind == "INTERP":
            self._advance()
            return _evaluate_interpolation(tok.value)
        if tok.kind == "IDENT":
            # ``rgba(r, g, b, a)`` looks like an ident followed by parens.
            if tok.value.lower() == "rgba" and self._peek(1).kind == "LPAREN":
                self._advance()  # rgba
                self._advance()  # (
                r = self._read_rgba_component()
                self._expect("COMMA")
                g = self._read_rgba_component()
                self._expect("COMMA")
                b = self._read_rgba_component()
                self._expect("COMMA")
                a = self._read_rgba_component()
                self._expect("RPAREN")
                return Color(r=int(r), g=int(g), b=int(b), a=float(a))
            self._advance()
            return tok.value
        raise DeclarativeThemeError(
            f"unexpected token {tok.kind} {tok.value!r}",
            line=tok.line, column=tok.column,
        )

    # --- theme composition ----------------------------------------------

    def _compose_theme(
        self,
        *,
        name: str,
        sections: dict[str, dict[str, Any]],
        sub_sections: dict[str, dict[str, dict[str, Any]]],
        list_sections: dict[str, list[str]],
    ) -> ThemeSpec:
        palette = _build_palette(sections.get("palette", {}))
        fonts = _build_fonts(sections.get("fonts", {}))
        frames = _build_frames(sub_sections.get("frames", {}))
        panels = _build_panels(sub_sections.get("panels", {}))
        shaders = _build_shaders(sub_sections.get("shader", {}))
        creatures = list_sections.get("creatures", [])
        stickers = list_sections.get("stickers", [])
        dividers = list_sections.get("dividers", [])

        # Compose SemanticTokens from the palette (using sensible fallbacks).
        semantic = _semantic_from_palette(palette)

        metadata: dict[str, str] = {"source": "declarative"}
        if panels:
            for kind, meta in panels.items():
                for entry_key, entry_val in meta.items():
                    metadata[f"panel.{kind}.{entry_key}"] = str(entry_val)
        if creatures:
            metadata["creature_roster"] = ",".join(creatures)
        if stickers:
            metadata["sticker_roster"] = ",".join(stickers)
        if dividers:
            metadata["divider_roster"] = ",".join(dividers)

        background_shader = shaders.get("background")

        return ThemeSpec(
            name=name,
            semantic=semantic,
            palette=palette,
            fonts=fonts,
            frames=frames,
            background_shader=background_shader,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Section → dataclass builders
# ---------------------------------------------------------------------------


def _build_palette(entries: dict[str, Any]) -> dict[str, Color]:
    out: dict[str, Color] = {}
    for key, value in entries.items():
        out[key.replace("-", "_")] = _to_color(value)
    return out


def _build_fonts(entries: dict[str, Any]) -> dict[str, Font]:
    out: dict[str, Font] = {}
    for key, value in entries.items():
        family: str
        size: int = 14
        weight: str = "regular"
        if isinstance(value, str):
            family = value
        elif isinstance(value, list):
            family = str(value[0]) if value and isinstance(value[0], str) \
                else "sans-serif"
            for v in value[1:]:
                if isinstance(v, (int, float)) and size == 14:
                    size = int(v)
                elif isinstance(v, str) and weight == "regular":
                    weight = v
        else:
            raise DeclarativeThemeError(
                f"fonts.{key}: expected string or compound value; got {value!r}"
            )
        out[key.replace("-", "_")] = Font(family=family, size=size,
                                          weight=weight)
    return out


def _build_frames(sub: dict[str, dict[str, Any]]) -> PanelFrameSet:
    kwargs: dict[str, FrameStyle] = {}
    for kind, entries in sub.items():
        style = _build_frame_style(entries)
        kwargs[kind.replace("-", "_")] = style
    if "default" not in kwargs:
        kwargs["default"] = FrameStyle()
    return PanelFrameSet(**kwargs)


def _build_frame_style(entries: dict[str, Any]) -> FrameStyle:
    fs = FrameStyle()
    fields: dict[str, Any] = {
        "border_size": fs.border_size,
        "border_color": fs.border_color,
        "rounding": fs.rounding,
        "padding_x": fs.padding_x,
        "padding_y": fs.padding_y,
        "shadow_size": fs.shadow_size,
        "shadow_color": fs.shadow_color,
        "child_rounding": fs.child_rounding,
        "child_border_size": fs.child_border_size,
        "grip_size": fs.grip_size,
        "grip_rounding": fs.grip_rounding,
        "title_bar_height": fs.title_bar_height,
    }
    for raw_key, value in entries.items():
        key = raw_key.replace("-", "_")
        if key == "border_size":
            fields["border_size"] = float(_numeric_scalar(value))
        elif key == "border_color":
            fields["border_color"] = _to_color(_last_color_token(value))
        elif key == "border":
            # Compound: "1px solid #E7DDF1" → capture size + colour.
            for part in _iter_value_parts(value):
                if isinstance(part, Color):
                    fields["border_color"] = part
                elif isinstance(part, (int, float)):
                    fields["border_size"] = float(part)
        elif key == "rounding":
            fields["rounding"] = float(_numeric_scalar(value))
        elif key == "padding":
            fields["padding_x"], fields["padding_y"] = _padding_pair(value)
        elif key == "padding_x":
            fields["padding_x"] = int(_numeric_scalar(value))
        elif key == "padding_y":
            fields["padding_y"] = int(_numeric_scalar(value))
        elif key == "shadow":
            size, color = _shadow_parts(value)
            if size is not None:
                fields["shadow_size"] = size
            if color is not None:
                fields["shadow_color"] = color
        elif key == "shadow_size":
            fields["shadow_size"] = float(_numeric_scalar(value))
        elif key == "shadow_color":
            fields["shadow_color"] = _to_color(value)
        elif key == "child_rounding":
            fields["child_rounding"] = float(_numeric_scalar(value))
        elif key == "child_border_size":
            fields["child_border_size"] = float(_numeric_scalar(value))
        elif key == "grip_size":
            fields["grip_size"] = float(_numeric_scalar(value))
        elif key == "grip_rounding":
            fields["grip_rounding"] = float(_numeric_scalar(value))
        elif key == "title_bar_height":
            fields["title_bar_height"] = int(_numeric_scalar(value))
        else:
            # Unknown key — record verbatim on metadata (soft-fail so
            # forward-compat authors can drop future keys in).
            continue
    return FrameStyle(**fields)


def _build_panels(sub: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for kind, entries in sub.items():
        out[kind] = {k.replace("-", "_"): _stringify(v) for k, v in entries.items()}
    return out


def _build_shaders(sub: dict[str, dict[str, Any]]) -> dict[str, ShaderEffect]:
    out: dict[str, ShaderEffect] = {}
    for slot, entries in sub.items():
        kind: str = "ruled_paper"
        params: dict[str, Any] = {}
        for key, value in entries.items():
            k = key.replace("-", "_")
            if k == "kind":
                kind = str(value) if not isinstance(value, list) else str(value[0])
            elif isinstance(value, Color):
                params[k] = (value.r, value.g, value.b,
                             int(round(value.a * 255)))
            elif isinstance(value, list):
                params[k] = [_stringify(v) for v in value]
            else:
                params[k] = _stringify(value)
        out[slot] = ShaderEffect(name=kind, params=params)
    return out


def _semantic_from_palette(palette: dict[str, Color]) -> SemanticTokens:
    """Best-effort compose a :class:`SemanticTokens` from a palette dict.

    Missing roles fall back to a neutral default so parsing a *minimal*
    theme (``palette { primary: #FF0000; }``) still yields a valid
    ThemeSpec.
    """
    def _get(key: str, fallback: tuple[int, int, int, float]) -> Color:
        if key in palette:
            return palette[key]
        r, g, b, a = fallback
        return Color(r=r, g=g, b=b, a=a)

    primary = _get("primary", (255, 111, 181, 1.0))
    secondary = _get("secondary", (231, 221, 241, 1.0))
    accent = _get("accent", (176, 122, 92, 1.0))
    background = _get("background", (251, 247, 236, 1.0))
    surface = _get("surface", background.as_rgba_tuple()[:3] + (1.0,))
    surface_hover = _get(
        "surface_hover", surface.as_rgba_tuple()[:3] + (1.0,)
    )
    border = _get("border", (200, 200, 200, 1.0))
    text_primary = _get("ink", (46, 41, 38, 1.0))
    text_primary = palette.get("text_primary", text_primary)
    text_secondary = _get("text_secondary", (92, 70, 48, 1.0))
    text_disabled = _get("text_disabled", (160, 142, 122, 1.0))
    success = _get("success", (122, 170, 102, 1.0))
    warning = _get("warning", (212, 160, 74, 1.0))
    error = _get("error", (184, 80, 64, 1.0))
    info = _get("info", (155, 178, 140, 1.0))
    focus_ring = _get("focus_ring", (primary.r, primary.g, primary.b, 1.0))
    glass_bg = _get("glass_bg", (background.r, background.g, background.b,
                                 0.85))
    gradient = Gradient(
        start=primary,
        end=accent,
        angle_deg=135.0,
    )
    return SemanticTokens(
        primary=primary,
        primary_gradient=gradient,
        secondary=secondary,
        accent=accent,
        background=background,
        surface=surface,
        surface_hover=surface_hover,
        border=border,
        text_primary=text_primary,
        text_secondary=text_secondary,
        text_disabled=text_disabled,
        success=success,
        warning=warning,
        error=error,
        info=info,
        focus_ring=focus_ring,
        glass_bg=glass_bg,
        glass_blur_px=10.0,
    )


# ---------------------------------------------------------------------------
# Value-shape helpers
# ---------------------------------------------------------------------------


def _iter_value_parts(value: Any) -> Iterable[Any]:
    if isinstance(value, list):
        yield from value
    else:
        yield value


def _numeric_scalar(value: Any) -> float:
    for part in _iter_value_parts(value):
        if isinstance(part, (int, float)):
            return float(part)
    raise DeclarativeThemeError(f"expected numeric value; got {value!r}")


def _last_color_token(value: Any) -> Color:
    for part in reversed(list(_iter_value_parts(value))):
        if isinstance(part, Color):
            return part
        if isinstance(part, str) and (part.startswith("#") or
                                       part.lower() in NAMED_COLORS):
            return _to_color(part)
    raise DeclarativeThemeError(f"expected colour value; got {value!r}")


def _padding_pair(value: Any) -> tuple[int, int]:
    parts = [p for p in _iter_value_parts(value)
             if isinstance(p, (int, float))]
    if not parts:
        raise DeclarativeThemeError(f"padding: expected numbers; got {value!r}")
    if len(parts) == 1:
        return int(parts[0]), int(parts[0])
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    if len(parts) == 4:
        # CSS: top, right, bottom, left → map to (x=right, y=top).
        top, right, _bottom, _left = parts
        return int(right), int(top)
    return int(parts[0]), int(parts[1])


def _shadow_parts(value: Any) -> tuple[float | None, Color | None]:
    """Extract (size, color) from a shadow value.

    ``shadow: 4px 0px rgba(255, 111, 181, 0.3);`` — the *max* numeric is
    treated as the shadow size (offsets aren't part of the FrameStyle),
    the colour is the RGBA argument.
    """
    size: float | None = None
    color: Color | None = None
    for part in _iter_value_parts(value):
        if isinstance(part, Color):
            color = part
        elif isinstance(part, (int, float)):
            candidate = float(part)
            if size is None or candidate > size:
                size = candidate
    return size, color


def _stringify(value: Any) -> Any:
    if isinstance(value, Color):
        return value  # keep Color intact for shader params
    if isinstance(value, list):
        return [_stringify(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# DeclarativeTheme — public entry
# ---------------------------------------------------------------------------


class DeclarativeTheme:
    """Parses a CSS-like theme string into a :class:`ThemeSpec`.

    See the module docstring for the full grammar reference; usage
    example::

        theme = DeclarativeTheme.parse('''
            @theme "my_cozy_theme" {
                palette {
                    primary: #FF6FB5;
                    secondary: #E7DDF1;
                    background: #FBF7EC;
                    ink: #1F2F66;
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
                shader.background {
                    kind: "ruled_paper";
                    line-color: #A7E7C7;
                }
                creatures {
                    fox_01, butterfly_01;
                }
            }
        ''')
    """

    @classmethod
    def parse(cls, source: str) -> ThemeSpec:
        """Parse *source* and return the resulting :class:`ThemeSpec`."""
        if not isinstance(source, str):
            raise DeclarativeThemeError(
                f"parse: source must be a str; got {type(source).__name__}"
            )
        tokens = _tokenize(source)
        return _Parser(tokens).parse()

    @classmethod
    def parse_file(cls, path: str | Path) -> ThemeSpec:
        """Read a ``.theme.css`` file from *path* and parse it."""
        p = Path(path)
        return cls.parse(p.read_text(encoding="utf-8"))

    @classmethod
    def dump(cls, theme: ThemeSpec) -> str:
        """Emit *theme* as a declarative source string.

        Round-trip guarantee: parsing the returned string yields a
        :class:`ThemeSpec` with the same palette / fonts / frames /
        background shader / metadata; auto-derived semantic tokens are
        recomputed from the palette on re-parse.
        """
        if not isinstance(theme, ThemeSpec):
            raise DeclarativeThemeError(
                f"dump: expected ThemeSpec; got {type(theme).__name__}"
            )
        parts: list[str] = []
        parts.append(f'@theme "{theme.name}" {{')

        # Palette --------------------------------------------------------
        if theme.palette:
            parts.append("    palette {")
            for key, color in theme.palette.items():
                parts.append(f"        {_key_out(key)}: {_color_out(color)};")
            parts.append("    }")

        # Fonts ----------------------------------------------------------
        if theme.fonts:
            parts.append("    fonts {")
            for key, font in theme.fonts.items():
                parts.append(
                    f'        {_key_out(key)}: "{font.family}", {font.size}, '
                    f'"{font.weight}";'
                )
            parts.append("    }")

        # Frames ---------------------------------------------------------
        for kind, style in _iter_frame_styles(theme.frames):
            parts.append(f"    frames.{kind} {{")
            parts.append(f"        border-size: {style.border_size}px;")
            if style.border_color is not None:
                parts.append(
                    f"        border-color: {_color_out(style.border_color)};"
                )
            parts.append(f"        rounding: {style.rounding}px;")
            parts.append(
                f"        padding: {style.padding_x}px {style.padding_y}px;"
            )
            if style.shadow_color is not None:
                parts.append(
                    f"        shadow: {style.shadow_size}px "
                    f"{_color_out(style.shadow_color)};"
                )
            else:
                parts.append(f"        shadow-size: {style.shadow_size}px;")
            parts.append(f"        child-rounding: {style.child_rounding}px;")
            parts.append(
                f"        child-border-size: {style.child_border_size}px;"
            )
            parts.append(f"        grip-size: {style.grip_size}px;")
            parts.append(f"        grip-rounding: {style.grip_rounding}px;")
            parts.append(f"        title-bar-height: {style.title_bar_height}px;")
            parts.append("    }")

        # Background shader ---------------------------------------------
        if theme.background_shader is not None:
            eff = theme.background_shader
            parts.append("    shader.background {")
            parts.append(f'        kind: "{eff.name}";')
            for pkey, pval in eff.params.items():
                parts.append(
                    f"        {_key_out(pkey)}: {_shader_param_out(pval)};"
                )
            parts.append("    }")

        # Roster metadata -----------------------------------------------
        for meta_key, section in (
            ("creature_roster", "creatures"),
            ("sticker_roster", "stickers"),
            ("divider_roster", "dividers"),
        ):
            raw = theme.metadata.get(meta_key)
            if not raw:
                continue
            items = [i.strip() for i in raw.split(",") if i.strip()]
            if items:
                parts.append(f"    {section} {{")
                parts.append("        " + ", ".join(items) + ";")
                parts.append("    }")

        parts.append("}")
        return "\n".join(parts) + "\n"


def _iter_frame_styles(frames: PanelFrameSet) -> Iterable[tuple[str, FrameStyle]]:
    yield "default", frames.default
    for kind in ("toolbar", "sidebar", "viewport", "modal", "code_pane",
                 "status_bar"):
        style = getattr(frames, kind)
        if style is not None:
            yield kind, style


def _key_out(key: str) -> str:
    return key.replace("_", "-")


def _color_out(color: Color) -> str:
    if color.a >= 0.9999:
        return f"#{color.r:02X}{color.g:02X}{color.b:02X}"
    return (f"rgba({color.r}, {color.g}, {color.b}, "
            f"{round(color.a, 4)})")


def _shader_param_out(value: Any) -> str:
    if isinstance(value, Color):
        return _color_out(value)
    if isinstance(value, (tuple, list)) and len(value) == 4 and all(
        isinstance(v, (int, float)) for v in value
    ):
        r, g, b, a = value
        if isinstance(a, int) and a > 1:
            a = a / 255.0
        color = Color(r=int(r), g=int(g), b=int(b), a=float(a))
        return _color_out(color)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value)


# ---------------------------------------------------------------------------
# Registry / cache integration
# ---------------------------------------------------------------------------


def load_declarative(path: str | Path) -> str:
    """Parse *path*, register the resulting theme, return its name.

    The parsed :meth:`ThemeSpec.to_dict` representation is written into
    ``~/.slappyengine/themes/<name>.cache.json`` as an advisory cache
    (parsing itself is fast — the cache is diagnostic rather than a
    speed-critical path).
    """
    from . import register_theme  # avoid circular import at module load

    theme = DeclarativeTheme.parse_file(path)
    register_theme(theme)
    try:
        cache_dir = Path(os.path.expanduser("~/.slappyengine/themes"))
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{theme.name}.cache.json"
        cache_path.write_text(
            json.dumps({"name": theme.name, "source_path": str(Path(path))}),
            encoding="utf-8",
        )
    except OSError:  # pragma: no cover - defensive: sandboxed FS
        pass
    return theme.name


__all__ = [
    "DeclarativeTheme",
    "DeclarativeThemeError",
    "NAMED_COLORS",
    "load_declarative",
]
