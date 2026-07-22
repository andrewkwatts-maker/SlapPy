"""Conflict detector for :class:`~pharos_engine.ui.hotkey_remap.HotkeyMap`.

This module (FF5) layers a *lint pass* over the AA7 hotkey map so the
editor UI can surface duplicate combos and combos that shadow well-known
platform / text-editing shortcuts before the user commits them.

The detector never mutates the map — it only inspects. Callers pick a
severity threshold (``"error"`` gates a Save, ``"warn"`` shows a yellow
badge, ``"info"`` is diagnostic only) and decide policy themselves.

Detected conflict kinds
-----------------------

* :attr:`ConflictKind.DUPLICATE_COMBO` — the same canonical combo bound
  to two or more distinct ``action_id`` values. Because
  :class:`HotkeyMap` collapses on combo insertion this only fires when
  callers assemble the report from *multiple* maps (see
  :func:`detect_conflicts` — it accepts either a single map or an
  iterable of maps).
* :attr:`ConflictKind.SHADOWS_PLATFORM` — combos the host OS already
  reserves (``alt+f4`` on Windows, ``cmd+q`` on macOS, ...). See
  :data:`PLATFORM_SHORTCUTS`.
* :attr:`ConflictKind.SHADOWS_TEXT_EDIT` — a single printable letter
  bound as a global shortcut. Any focused text field will lose that
  keypress to the editor, which is nearly always a bug.
* :attr:`ConflictKind.MODIFIER_MISSING` — a "danger-zone" key (space /
  enter / escape / tab) bound *without* a modifier. Editors overwhelming
  need these keys free for line insertion / focus dismissal.
* :attr:`ConflictKind.ORPHAN_CHORD` — a multi-chord combo like
  ``ctrl+x ctrl+s`` exists in the map but the leading chord ``ctrl+x``
  is *also* bound to a different action. Pressing ``ctrl+x`` then
  becomes ambiguous (fire the single action, or wait for the follow-up
  chord?). We flag both sides so the caller can pick a rewrite.

Design notes
------------

* The module has no side-effects at import time and never touches the
  filesystem — the caller passes an already-loaded :class:`HotkeyMap`.
* Platform detection defaults to :func:`sys.platform` mapping (``win32``
  → ``"win"``, ``darwin`` → ``"mac"``, everything else → ``"linux"``)
  but callers can override via the ``platform`` kwarg for cross-OS
  linting in CI.
* All strings emitted by :func:`format_report` are ASCII so the output
  round-trips through Windows console encodings without hitting the
  cp1252 encode-error trap.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable

from pharos_engine.ui.hotkey_remap import HotkeyBinding, HotkeyMap


# ---------------------------------------------------------------------------
# Enums + dataclasses
# ---------------------------------------------------------------------------


class ConflictKind(Enum):
    """The kind of conflict :func:`detect_conflicts` uncovered."""

    DUPLICATE_COMBO    = "duplicate_combo"
    SHADOWS_PLATFORM   = "shadows_platform"
    SHADOWS_TEXT_EDIT  = "shadows_text_edit"
    MODIFIER_MISSING   = "modifier_missing"
    ORPHAN_CHORD       = "orphan_chord"


#: Valid severity tokens. Ordered by increasing gravity so callers can
#: compute a max via ``max(_SEVERITY_ORDER.index(s) for s in ...)``.
_SEVERITY_ORDER: tuple[str, ...] = ("info", "warn", "error")


@dataclass(frozen=True)
class ConflictReport:
    """One conflict finding.

    Attributes
    ----------
    combo:
        The canonical combo that triggered the finding. For a
        :attr:`ConflictKind.DUPLICATE_COMBO` this is the shared combo;
        for :attr:`ConflictKind.ORPHAN_CHORD` this is the *offending*
        combo (the ambiguous prefix, when both are flagged).
    kind:
        Which detector fired.
    severity:
        One of ``"info"`` / ``"warn"`` / ``"error"``.
    message:
        Human-readable one-line explanation. Suitable for tooltip
        display in the editor.
    bindings:
        Every :class:`HotkeyBinding` implicated in the finding. Length
        is 1 for the single-binding checks and 2+ for
        :attr:`ConflictKind.DUPLICATE_COMBO` / orphan-chord pairs.
    """

    combo:     str
    kind:      ConflictKind
    severity:  str
    message:   str
    bindings:  list[HotkeyBinding] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.combo, str) or not self.combo:
            raise ValueError("ConflictReport: combo must be a non-empty str")
        if not isinstance(self.kind, ConflictKind):
            raise TypeError(
                "ConflictReport: kind must be ConflictKind; got "
                f"{type(self.kind).__name__}"
            )
        if self.severity not in _SEVERITY_ORDER:
            raise ValueError(
                f"ConflictReport: severity must be one of {_SEVERITY_ORDER}; "
                f"got {self.severity!r}"
            )
        if not isinstance(self.message, str) or not self.message:
            raise ValueError(
                "ConflictReport: message must be a non-empty str"
            )
        if not isinstance(self.bindings, list):
            raise TypeError(
                "ConflictReport: bindings must be a list; got "
                f"{type(self.bindings).__name__}"
            )
        for b in self.bindings:
            if not isinstance(b, HotkeyBinding):
                raise TypeError(
                    "ConflictReport: every binding must be HotkeyBinding; "
                    f"got {type(b).__name__}"
                )


# ---------------------------------------------------------------------------
# Platform-shortcut reservations
# ---------------------------------------------------------------------------


#: Well-known OS-level shortcuts we refuse to hijack, keyed by platform
#: token (``"win"`` / ``"mac"`` / ``"linux"``). Values are the canonical
#: form emitted by :func:`pharos_engine.ui.hotkey_remap._canon_combo`
#: (lower-cased tokens, modifier order ``ctrl / shift / alt / meta``,
#: with ``cmd`` folded to ``meta``).
PLATFORM_SHORTCUTS: dict[str, set[str]] = {
    "win": {
        "alt+f4",
        "ctrl+alt+delete",
        "ctrl+shift+escape",
        "meta+l",              # Win+L → lock workstation
        "meta+d",              # Win+D → show desktop
        "meta+e",              # Win+E → file explorer
        "meta+r",              # Win+R → run dialog
        "meta+tab",            # Win+Tab → task view
        "alt+tab",             # Alt+Tab → app switcher
        "ctrl+shift+n",        # New folder in Explorer
        "printscreen",
    },
    "mac": {
        "meta+q",              # Cmd+Q → quit
        "meta+w",              # Cmd+W → close window
        "meta+tab",            # Cmd+Tab → app switcher
        "meta+space",          # Cmd+Space → Spotlight
        "meta+h",              # Cmd+H → hide window
        "meta+m",              # Cmd+M → minimise
        "meta+option+escape",  # force-quit dialog
        "meta+shift+3",        # screenshot
        "meta+shift+4",        # screenshot area
        "meta+shift+5",        # screenshot HUD
        "ctrl+meta+q",         # lock screen
    },
    "linux": {
        "ctrl+alt+t",          # terminal
        "ctrl+alt+delete",     # legacy X shortcut
        "ctrl+alt+backspace",  # kill X server (still enabled on some distros)
        "ctrl+alt+f1",
        "ctrl+alt+f2",
        "ctrl+alt+f7",         # VT switching
        "meta+l",
        "meta+d",
        "meta+tab",
        "alt+tab",
        "alt+f2",              # KDE run dialog
        "alt+f4",              # KDE / GNOME close window
        "printscreen",
    },
}


#: "Danger-zone" leaf keys that overwhelmingly need to stay bare so
#: text-editing works. Bound *without* a modifier they eat every space
#: or Enter keypress the user makes.
_DANGER_ZONE_KEYS: frozenset[str] = frozenset({
    "space",
    "enter",
    "escape",
    "tab",
})


#: Canonical modifier tokens. Local copy so this module never touches
#: the private ``_MODIFIER_ORDER`` in :mod:`hotkey_remap`.
_MODIFIER_TOKENS: frozenset[str] = frozenset({
    "ctrl", "shift", "alt", "meta",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_platform(platform: str | None) -> str:
    """Return a normalised platform token (``"win"`` / ``"mac"`` / ``"linux"``)."""
    if platform is not None:
        p = platform.strip().lower()
        if p in PLATFORM_SHORTCUTS:
            return p
        # Common aliases callers might pass.
        alias = {
            "windows": "win",
            "win32":   "win",
            "darwin":  "mac",
            "osx":     "mac",
            "macos":   "mac",
        }.get(p)
        if alias is not None:
            return alias
        # Unknown platform → treat as linux (safest baseline).
        return "linux"
    raw = sys.platform.lower()
    if raw.startswith("win"):
        return "win"
    if raw == "darwin":
        return "mac"
    return "linux"


def _split_chords(combo: str) -> list[str]:
    """Return the list of chords in *combo* (space-separated)."""
    return [c for c in combo.split() if c]


def _split_chord(chord: str) -> tuple[list[str], str | None]:
    """Return ``(modifiers, leaf)`` for a single canonical chord.

    Callers assume the chord is already canonical (produced by
    ``_canon_combo`` on the way into :class:`HotkeyBinding`). Modifier
    tokens land in the ``modifiers`` list in insertion order; the leaf
    is whatever remains, or ``None`` for pure-modifier chords like
    ``"ctrl"``.
    """
    parts = [p for p in chord.split("+") if p]
    mods: list[str] = []
    leaf: str | None = None
    for tok in parts:
        if tok in _MODIFIER_TOKENS:
            mods.append(tok)
        else:
            leaf = tok
    return mods, leaf


def _is_printable_letter(leaf: str) -> bool:
    """Return ``True`` when *leaf* is exactly one ASCII letter/digit."""
    if len(leaf) != 1:
        return False
    return leaf.isalnum()


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


def detect_conflicts(
    map: HotkeyMap | Iterable[HotkeyMap],
    *,
    platform: str | None = None,
) -> list[ConflictReport]:
    """Return every conflict :class:`ConflictReport` for *map*.

    Parameters
    ----------
    map:
        Either a single :class:`HotkeyMap` (the common case) or an
        iterable of maps. Passing multiple maps lets callers detect
        duplicate-combo conflicts across a "default + user" pair *before*
        the merge collapses them.
    platform:
        Override the reserved-combo table lookup. Defaults to detecting
        the host OS via :func:`sys.platform`. Accepted values:
        ``"win"`` / ``"mac"`` / ``"linux"`` plus the aliases documented
        in :func:`_detect_platform`.
    """
    plat_token = _detect_platform(platform)
    reserved = PLATFORM_SHORTCUTS.get(plat_token, set())

    # Normalise input into a flat list of bindings (respecting
    # enabled-flag: disabled rows are ignored — they can never conflict
    # because the resolver returns ``None`` for them).
    if isinstance(map, HotkeyMap):
        maps: list[HotkeyMap] = [map]
    else:
        maps = list(map)
        for i, m in enumerate(maps):
            if not isinstance(m, HotkeyMap):
                raise TypeError(
                    "detect_conflicts: every map must be HotkeyMap; index "
                    f"{i} is {type(m).__name__}"
                )

    # Gather (combo -> [binding, ...]) across every input map.
    per_combo: dict[str, list[HotkeyBinding]] = {}
    for m in maps:
        for b in m.list_all():
            if not b.enabled:
                continue
            per_combo.setdefault(b.combo, []).append(b)

    reports: list[ConflictReport] = []

    # --- DUPLICATE_COMBO -------------------------------------------------
    for combo, bindings in per_combo.items():
        action_ids = {b.action_id for b in bindings}
        if len(action_ids) > 1:
            reports.append(ConflictReport(
                combo=combo,
                kind=ConflictKind.DUPLICATE_COMBO,
                severity="error",
                message=(
                    f"{combo!r} is bound to multiple actions: "
                    + ", ".join(sorted(action_ids))
                ),
                bindings=list(bindings),
            ))

    # --- SHADOWS_PLATFORM -----------------------------------------------
    for combo, bindings in per_combo.items():
        if combo in reserved:
            reports.append(ConflictReport(
                combo=combo,
                kind=ConflictKind.SHADOWS_PLATFORM,
                severity="error",
                message=(
                    f"{combo!r} shadows the {plat_token!r} platform-level "
                    "shortcut — the OS will consume it before the editor sees it"
                ),
                bindings=list(bindings),
            ))

    # --- SHADOWS_TEXT_EDIT + MODIFIER_MISSING (single-chord checks) ---
    for combo, bindings in per_combo.items():
        chords = _split_chords(combo)
        if len(chords) != 1:
            continue
        mods, leaf = _split_chord(chords[0])
        if leaf is None:
            # Pure modifier chord — nothing to check here.
            continue
        if not mods:
            # No modifier at all.
            if leaf in _DANGER_ZONE_KEYS:
                reports.append(ConflictReport(
                    combo=combo,
                    kind=ConflictKind.MODIFIER_MISSING,
                    severity="error",
                    message=(
                        f"{combo!r} binds a danger-zone key ({leaf!r}) "
                        "without a modifier — text input will break"
                    ),
                    bindings=list(bindings),
                ))
            elif _is_printable_letter(leaf):
                reports.append(ConflictReport(
                    combo=combo,
                    kind=ConflictKind.SHADOWS_TEXT_EDIT,
                    severity="warn",
                    message=(
                        f"{combo!r} binds a bare printable key ({leaf!r}) — "
                        "any focused text field will lose the keypress"
                    ),
                    bindings=list(bindings),
                ))

    # --- ORPHAN_CHORD ---------------------------------------------------
    # For every multi-chord combo, flag it when the *leading* chord is
    # also bound as a single-chord combo pointing at a different action
    # — pressing the leading chord then becomes ambiguous.
    single_chord_leaders: dict[str, list[HotkeyBinding]] = {
        combo: bindings
        for combo, bindings in per_combo.items()
        if len(_split_chords(combo)) == 1
    }
    for combo, bindings in per_combo.items():
        chords = _split_chords(combo)
        if len(chords) < 2:
            continue
        leader = chords[0]
        if leader in single_chord_leaders:
            leader_bindings = single_chord_leaders[leader]
            reports.append(ConflictReport(
                combo=combo,
                kind=ConflictKind.ORPHAN_CHORD,
                severity="warn",
                message=(
                    f"{combo!r} starts with the standalone chord {leader!r} "
                    "which is already bound — pressing the leader becomes "
                    "ambiguous"
                ),
                bindings=list(bindings) + list(leader_bindings),
            ))

    # Stable, deterministic ordering by (kind, combo).
    reports.sort(key=lambda r: (r.kind.value, r.combo))
    return reports


# ---------------------------------------------------------------------------
# Report utilities
# ---------------------------------------------------------------------------


#: Human-readable severity glyphs. ASCII-only so the output survives
#: Windows console cp1252.
_SEVERITY_GLYPH: dict[str, str] = {
    "error": "[ERR ]",
    "warn":  "[WARN]",
    "info":  "[INFO]",
}


def format_report(reports: Iterable[ConflictReport]) -> str:
    """Return a pretty-printed multi-line render of *reports*.

    The output groups by :class:`ConflictKind` in the order the kinds
    are declared in the enum. Empty inputs return an explicit
    ``"No conflicts."`` sentinel so callers can distinguish
    "detector ran and found nothing" from "detector never ran".
    """
    rlist = list(reports)
    for r in rlist:
        if not isinstance(r, ConflictReport):
            raise TypeError(
                "format_report: every entry must be a ConflictReport; got "
                f"{type(r).__name__}"
            )
    if not rlist:
        return "No conflicts."

    lines: list[str] = []
    by_kind: dict[ConflictKind, list[ConflictReport]] = {}
    for r in rlist:
        by_kind.setdefault(r.kind, []).append(r)

    for kind in ConflictKind:
        bucket = by_kind.get(kind)
        if not bucket:
            continue
        lines.append(f"== {kind.name} ({len(bucket)}) ==")
        for r in bucket:
            glyph = _SEVERITY_GLYPH.get(r.severity, "[    ]")
            lines.append(f"  {glyph} {r.combo}: {r.message}")
            for b in r.bindings:
                lines.append(
                    f"      - action={b.action_id!r} source={b.source!r}"
                )
    return "\n".join(lines)


def has_severity(
    reports: Iterable[ConflictReport],
    severity: str,
) -> bool:
    """Return ``True`` when *reports* contains any entry ``>= severity``.

    Severity ordering is ``info < warn < error``. Passing ``"warn"`` returns
    ``True`` if any warning *or* error is present. Unknown severity strings
    raise :class:`ValueError` so callers can't silently miss a typo.
    """
    if severity not in _SEVERITY_ORDER:
        raise ValueError(
            f"has_severity: severity must be one of {_SEVERITY_ORDER}; "
            f"got {severity!r}"
        )
    threshold = _SEVERITY_ORDER.index(severity)
    for r in reports:
        if not isinstance(r, ConflictReport):
            raise TypeError(
                "has_severity: every entry must be a ConflictReport; got "
                f"{type(r).__name__}"
            )
        if _SEVERITY_ORDER.index(r.severity) >= threshold:
            return True
    return False


def filter_by_kind(
    reports: Iterable[ConflictReport],
    kind: ConflictKind,
) -> list[ConflictReport]:
    """Return the sub-list of *reports* whose ``.kind`` matches *kind*."""
    if not isinstance(kind, ConflictKind):
        raise TypeError(
            "filter_by_kind: kind must be ConflictKind; got "
            f"{type(kind).__name__}"
        )
    out: list[ConflictReport] = []
    for r in reports:
        if not isinstance(r, ConflictReport):
            raise TypeError(
                "filter_by_kind: every entry must be a ConflictReport; got "
                f"{type(r).__name__}"
            )
        if r.kind is kind:
            out.append(r)
    return out


__all__ = [
    "ConflictKind",
    "ConflictReport",
    "PLATFORM_SHORTCUTS",
    "detect_conflicts",
    "filter_by_kind",
    "format_report",
    "has_severity",
]
