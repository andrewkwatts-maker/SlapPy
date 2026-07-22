"""User-remappable hotkey system for the SlapPyEngine editor.

The :mod:`pharos_editor.ui.user_overrides` layer (X6) already loads user
YAML hotkey files from ``~/.pharos_engine/ui/hotkeys/`` and folds them
into :class:`~pharos_editor.ui.editor.notebook_hotkeys.NotebookHotkeys`.
This module (AA7) is the *typed* layer sitting on top: it introduces a
proper :class:`HotkeyBinding` dataclass, a :class:`HotkeyMap` container
with add / remove / resolve / merge / round-trip helpers, a validator
that checks every ``action_id`` against
:data:`pharos_editor.tool_router.REGISTRY`, a first-launch
:func:`bake_defaults` bootstrapper, and a :class:`HotkeyRemapWatcher`
that subclasses the X6 :class:`~pharos_editor.ui.user_overrides.WatcherHandle`
so downstream consumers see one unified handle type.

Directory layout
----------------

::

    ~/.pharos_engine/ui/hotkeys/
    ├── default.yaml         # copied from baked/ on first launch
    ├── vim_style.yaml       # copied from baked/ on first launch
    ├── emacs_style.yaml     # copied from baked/ on first launch
    ├── my_custom.yaml       # any user file — merged on top
    └── commands.py          # optional (owned by X6)

    python/pharos_engine/ui/hotkeys/baked/
    ├── default.yaml         # mirrors NotebookHotkeys.DEFAULT_HOTKEYS
    ├── vim_style.yaml       # hjkl + gg + dd combos
    └── emacs_style.yaml     # M-x + C-x C-s combos

YAML format
-----------

Two shapes are accepted so users can pick the terser one:

1. Flat mapping::

       ctrl+s: editor.save
       ctrl+z: editor.undo

2. Explicit rows (matches :class:`HotkeyBinding`)::

       bindings:
         - combo: ctrl+s
           action_id: editor.save
           enabled: true
         - combo: ctrl+z
           action_id: editor.undo

Both shapes round-trip through :meth:`HotkeyMap.from_yaml` /
:meth:`HotkeyMap.to_yaml`. The explicit shape is preserved on write when
any binding carries a non-default ``enabled`` / ``source`` field.

Merge semantics
---------------

:func:`apply_remap` performs a **user-wins** merge: the user map's
bindings overlay the defaults keyed by *combo*. When a user binding
disables (``enabled=False``) an existing default it is dropped from the
merged map rather than shadowed — this lets users clear a combo they
don't want the editor to consume.

Design provenance
-----------------

* AA-batch sprint (2026-07-05) — user directive: "extend user-overrides
  so users can remap hotkey combos to any registered ToolRouter action
  via YAML."
* Hard boundary: this module never imports from
  :mod:`pharos_editor.ui.user_overrides` at module scope. The subclassed
  watcher is built by re-using :meth:`UserOverrideLoader.watch_dir` at
  call time so tests can import this module without dragging watchdog /
  DPG into the graph.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

from pharos_engine._validation import (
    validate_bool,
    validate_non_empty_str,
    validate_path_like,
    validate_str,
)


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------------


#: Modifier tokens in the canonical order emitted by :func:`_canon_combo`.
_MODIFIER_ORDER: tuple[str, ...] = ("ctrl", "shift", "alt", "meta")


#: Character aliases so users can type either form in YAML and hit the
#: same canonical combo. Extend cautiously — every entry becomes a public
#: contract.
_KEY_ALIASES: dict[str, str] = {
    "control": "ctrl",
    "cmd":     "meta",
    "command": "meta",
    "super":   "meta",
    "win":     "meta",
    "esc":     "escape",
    "return":  "enter",
}


def _canon_combo(combo: str) -> str:
    """Return the canonical ``ctrl+shift+alt+<key>`` form for *combo*.

    * lower-cases every token,
    * expands aliases via :data:`_KEY_ALIASES`,
    * drops duplicates,
    * reorders modifiers into :data:`_MODIFIER_ORDER`,
    * places the non-modifier "leaf" key last.

    Multi-chord combos (``"ctrl+x ctrl+s"``) are canonicalised per chord
    and re-joined with a single space so ``"CTRL+X CTRL+S"`` and
    ``"ctrl+x  ctrl+s"`` collapse to the same key.
    """
    if not isinstance(combo, str):
        raise TypeError(
            f"HotkeyBinding: combo must be str; got {type(combo).__name__}"
        )
    stripped = combo.strip()
    if not stripped:
        raise ValueError("HotkeyBinding: combo must be non-empty")
    # Split on whitespace to catch multi-chord bindings.
    chords = [c for c in stripped.split() if c]
    canon_chords: list[str] = []
    for chord in chords:
        parts = [p.strip().lower() for p in chord.split("+") if p.strip()]
        parts = [_KEY_ALIASES.get(p, p) for p in parts]
        mods_seen: list[str] = []
        leaves: list[str] = []
        for tok in parts:
            if tok in _MODIFIER_ORDER:
                if tok not in mods_seen:
                    mods_seen.append(tok)
            else:
                leaves.append(tok)
        # Reorder mods.
        mods_ordered = [m for m in _MODIFIER_ORDER if m in mods_seen]
        if leaves:
            # Take the *last* leaf as the key; earlier leaves fold into
            # mods_ordered so callers can pass "ctrl+s+shift" and still hit
            # "ctrl+shift+s".
            leaf = leaves[-1]
            extra = leaves[:-1]
            for e in extra:
                if e in _MODIFIER_ORDER and e not in mods_ordered:
                    mods_ordered.append(e)
            canon_chords.append("+".join(mods_ordered + [leaf]))
        else:
            if not mods_ordered:
                raise ValueError(
                    f"HotkeyBinding: combo {combo!r} has no key tokens"
                )
            canon_chords.append("+".join(mods_ordered))
    return " ".join(canon_chords)


# ---------------------------------------------------------------------------
# HotkeyBinding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HotkeyBinding:
    """One row of the hotkey remap table.

    Attributes
    ----------
    combo:
        Canonical key combo (e.g. ``"ctrl+shift+m"``). Constructor
        normalises whatever the user types.
    action_id:
        The :class:`~pharos_editor.tool_router.ToolAction` identifier the
        combo should dispatch. Must be non-empty.
    enabled:
        When ``False`` the binding disables any conflicting default —
        useful for stripping a combo without replacing it.
    source:
        Free-form provenance tag ("user", "default", "vim_style", ...).
        Preserved through YAML round-trip so the editor UI can surface
        "reset to baked" affordances.
    """

    combo:     str
    action_id: str
    enabled:   bool = True
    source:    str = "user"

    def __post_init__(self) -> None:
        # Frozen dataclass — use object.__setattr__ for normalisation.
        object.__setattr__(
            self,
            "combo",
            _canon_combo(
                validate_non_empty_str("combo", "HotkeyBinding", self.combo)
            ),
        )
        object.__setattr__(
            self,
            "action_id",
            validate_non_empty_str(
                "action_id", "HotkeyBinding", self.action_id
            ),
        )
        object.__setattr__(
            self,
            "enabled",
            validate_bool("enabled", "HotkeyBinding", self.enabled),
        )
        object.__setattr__(
            self,
            "source",
            validate_str("source", "HotkeyBinding", self.source, allow_empty=False),
        )


# ---------------------------------------------------------------------------
# HotkeyMap
# ---------------------------------------------------------------------------


class HotkeyMap:
    """Ordered container of :class:`HotkeyBinding` rows.

    The map is keyed by canonical combo so ``add`` / ``resolve`` /
    ``remove`` are O(1). Insertion order is preserved for round-trip
    stability.
    """

    def __init__(
        self,
        bindings: Iterable[HotkeyBinding] | None = None,
    ) -> None:
        self._bindings: dict[str, HotkeyBinding] = {}
        if bindings is not None:
            for b in bindings:
                self.add(b)

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def add(self, binding: HotkeyBinding) -> None:
        """Insert *binding* (overwriting any existing combo)."""
        if not isinstance(binding, HotkeyBinding):
            raise TypeError(
                "HotkeyMap.add: binding must be HotkeyBinding; got "
                f"{type(binding).__name__}"
            )
        self._bindings[binding.combo] = binding

    def remove(self, combo: str) -> bool:
        """Drop the row for *combo*. Returns ``True`` iff present."""
        canon = _canon_combo(validate_non_empty_str(
            "combo", "HotkeyMap.remove", combo,
        ))
        return self._bindings.pop(canon, None) is not None

    def clear(self) -> None:
        """Drop every binding."""
        self._bindings.clear()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def resolve(self, combo: str) -> str | None:
        """Return the ``action_id`` bound to *combo* (or ``None``).

        Disabled bindings (``enabled=False``) return ``None`` — from the
        caller's perspective a disabled row is indistinguishable from an
        absent row.
        """
        canon = _canon_combo(validate_non_empty_str(
            "combo", "HotkeyMap.resolve", combo,
        ))
        b = self._bindings.get(canon)
        if b is None or not b.enabled:
            return None
        return b.action_id

    def get(self, combo: str) -> HotkeyBinding | None:
        """Return the :class:`HotkeyBinding` for *combo* — enabled or not."""
        canon = _canon_combo(validate_non_empty_str(
            "combo", "HotkeyMap.get", combo,
        ))
        return self._bindings.get(canon)

    def list_all(self) -> list[HotkeyBinding]:
        """Return every binding in insertion order."""
        return list(self._bindings.values())

    def combos(self) -> list[str]:
        """Return every canonical combo in insertion order."""
        return list(self._bindings.keys())

    def __len__(self) -> int:
        return len(self._bindings)

    def __contains__(self, combo: object) -> bool:
        if not isinstance(combo, str):
            return False
        try:
            canon = _canon_combo(combo)
        except (ValueError, TypeError):
            return False
        return canon in self._bindings

    def __iter__(self) -> Iterator[HotkeyBinding]:
        return iter(self._bindings.values())

    # ------------------------------------------------------------------
    # Merge
    # ------------------------------------------------------------------

    def merge(self, other: "HotkeyMap") -> "HotkeyMap":
        """Return a *new* map with *other* layered on top of ``self``.

        User-wins semantics: for every combo present in *other*, the
        other-side binding wins. Disabled other-side bindings *remove*
        the combo from the merged map (rather than shadow it) so users
        can clear a shortcut without replacing it.
        """
        if not isinstance(other, HotkeyMap):
            raise TypeError(
                "HotkeyMap.merge: other must be HotkeyMap; got "
                f"{type(other).__name__}"
            )
        merged = HotkeyMap(self.list_all())
        for b in other.list_all():
            if not b.enabled:
                merged._bindings.pop(b.combo, None)
                continue
            merged._bindings[b.combo] = b
        return merged

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------

    def to_yaml(self) -> str:
        """Serialise the map to YAML.

        The explicit ``bindings:`` shape is used when any row carries a
        non-default ``enabled`` / ``source``; otherwise the terser flat
        mapping is emitted so hand-written files stay hand-writable.
        """
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "HotkeyMap.to_yaml: PyYAML is required — install with "
                "`pip install pyyaml`."
            ) from exc

        needs_explicit = any(
            (not b.enabled) or (b.source != "user")
            for b in self._bindings.values()
        )
        if needs_explicit:
            payload = {
                "bindings": [
                    {
                        "combo":     b.combo,
                        "action_id": b.action_id,
                        "enabled":   b.enabled,
                        "source":    b.source,
                    }
                    for b in self._bindings.values()
                ]
            }
        else:
            payload = {b.combo: b.action_id for b in self._bindings.values()}
        return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)

    @classmethod
    def from_yaml(
        cls,
        text: str,
        *,
        default_source: str = "user",
    ) -> "HotkeyMap":
        """Parse *text* into a fresh :class:`HotkeyMap`.

        Accepts either the flat mapping or the explicit ``bindings:``
        list shape. Malformed rows (missing ``combo`` / ``action_id``,
        non-string values) are skipped with a WARNING to :mod:`logging`
        — the map is still returned so a single stray line never breaks
        the boot.
        """
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "HotkeyMap.from_yaml: PyYAML is required — install with "
                "`pip install pyyaml`."
            ) from exc
        if not isinstance(text, str):
            raise TypeError(
                "HotkeyMap.from_yaml: text must be str; got "
                f"{type(text).__name__}"
            )
        data = yaml.safe_load(text) or {}
        m = cls()
        if isinstance(data, dict) and "bindings" in data and isinstance(
            data["bindings"], list
        ):
            for row in data["bindings"]:
                if not isinstance(row, dict):
                    _log.warning(
                        "HotkeyMap.from_yaml: skipping non-mapping row %r",
                        row,
                    )
                    continue
                combo = row.get("combo")
                action_id = row.get("action_id")
                if not isinstance(combo, str) or not isinstance(action_id, str):
                    _log.warning(
                        "HotkeyMap.from_yaml: skipping row missing combo/"
                        "action_id: %r", row,
                    )
                    continue
                enabled = bool(row.get("enabled", True))
                source = str(row.get("source", default_source))
                try:
                    m.add(HotkeyBinding(
                        combo=combo,
                        action_id=action_id,
                        enabled=enabled,
                        source=source,
                    ))
                except (ValueError, TypeError) as exc:
                    _log.warning(
                        "HotkeyMap.from_yaml: skipping invalid row %r: %s",
                        row, exc,
                    )
            return m
        if isinstance(data, dict):
            for combo, action_id in data.items():
                if not isinstance(combo, str) or not isinstance(action_id, str):
                    _log.warning(
                        "HotkeyMap.from_yaml: skipping non-string entry "
                        "%r -> %r", combo, action_id,
                    )
                    continue
                try:
                    m.add(HotkeyBinding(
                        combo=combo,
                        action_id=action_id,
                        source=default_source,
                    ))
                except (ValueError, TypeError) as exc:
                    _log.warning(
                        "HotkeyMap.from_yaml: skipping invalid entry "
                        "%r -> %r: %s", combo, action_id, exc,
                    )
            return m
        _log.warning(
            "HotkeyMap.from_yaml: root is not a mapping (%s) — empty map",
            type(data).__name__,
        )
        return m

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, router: Any) -> list[str]:
        """Return a list of ``action_id`` values *router* does not know.

        The router is duck-typed: any object with a callable
        ``has_action(action_id) -> bool`` method is accepted. Duplicates
        are collapsed in the returned list.

        An empty return value means every binding maps to a live action
        (or the map is empty).
        """
        has_action = getattr(router, "has_action", None)
        if not callable(has_action):
            raise TypeError(
                "HotkeyMap.validate: router must expose has_action(str) — "
                "did you forget to pass pharos_editor.tool_router.REGISTRY?"
            )
        seen: set[str] = set()
        unknown: list[str] = []
        for b in self._bindings.values():
            if b.action_id in seen:
                continue
            seen.add(b.action_id)
            try:
                ok = bool(has_action(b.action_id))
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "HotkeyMap.validate: router.has_action(%r) raised %s",
                    b.action_id, exc,
                )
                ok = False
            if not ok:
                unknown.append(b.action_id)
        return unknown


# ---------------------------------------------------------------------------
# Directory bootstrap + loading
# ---------------------------------------------------------------------------


#: The user-editable directory. Users may edit any ``*.yaml`` file inside.
USER_HOTKEY_DIR: Path = Path.home() / ".pharos_engine" / "ui" / "hotkeys"


#: The read-only baked directory shipped inside the wheel.
BAKED_HOTKEY_DIR: Path = Path(__file__).parent / "hotkeys" / "baked"


def _atomic_write_text(target: Path, text: str) -> None:
    """Write *text* to *target* atomically (temp + rename)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def bake_defaults(user_dir: Path | str | None = None) -> list[Path]:
    """Copy every ``baked/*.yaml`` into *user_dir* (missing files only).

    Idempotent: existing user files are never overwritten. Returns the
    list of paths freshly copied on this call (empty on subsequent
    launches).
    """
    if user_dir is None:
        target_dir = USER_HOTKEY_DIR
    else:
        target_dir = Path(validate_path_like(
            "user_dir", "bake_defaults", user_dir,
        ))
    target_dir.mkdir(parents=True, exist_ok=True)
    if not BAKED_HOTKEY_DIR.is_dir():
        _log.warning(
            "bake_defaults: baked dir %s does not exist — nothing to copy",
            BAKED_HOTKEY_DIR,
        )
        return []
    copied: list[Path] = []
    for src in sorted(BAKED_HOTKEY_DIR.iterdir()):
        if not src.is_file() or src.suffix.lower() not in {".yaml", ".yml"}:
            continue
        dest = target_dir / src.name
        if dest.exists():
            continue
        try:
            text = src.read_text(encoding="utf-8")
        except OSError as exc:
            _log.warning(
                "bake_defaults: cannot read baked %s: %s", src, exc,
            )
            continue
        try:
            _atomic_write_text(dest, text)
        except OSError as exc:
            _log.warning(
                "bake_defaults: cannot write %s: %s", dest, exc,
            )
            continue
        copied.append(dest)
    return copied


def load_user_hotkeys(user_dir: Path | str | None = None) -> HotkeyMap:
    """Load every ``*.yaml`` under *user_dir* into one merged map.

    Files are read in sorted-filename order; later files win on combo
    collisions. Missing directories yield an empty map. Individual file
    parse errors are logged + skipped so a single corrupt file never
    breaks the boot.
    """
    if user_dir is None:
        directory = USER_HOTKEY_DIR
    else:
        directory = Path(validate_path_like(
            "user_dir", "load_user_hotkeys", user_dir,
        ))
    if not directory.is_dir():
        return HotkeyMap()
    merged = HotkeyMap()
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        # Derive default source from filename stem so "vim_style.yaml"
        # bindings carry source="vim_style" through round-trip.
        default_source = path.stem
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            _log.warning(
                "load_user_hotkeys: cannot read %s: %s", path, exc,
            )
            continue
        try:
            partial = HotkeyMap.from_yaml(text, default_source=default_source)
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "load_user_hotkeys: cannot parse %s: %s", path, exc,
            )
            continue
        for b in partial.list_all():
            merged.add(b)
    return merged


def apply_remap(default_map: HotkeyMap, user_map: HotkeyMap) -> HotkeyMap:
    """Return ``default_map.merge(user_map)`` — user wins per combo.

    Thin convenience wrapper so callers can express the intent
    (``apply_remap(defaults, user)``) without having to remember which
    side of ``merge`` is dominant.
    """
    if not isinstance(default_map, HotkeyMap):
        raise TypeError(
            "apply_remap: default_map must be HotkeyMap; got "
            f"{type(default_map).__name__}"
        )
    if not isinstance(user_map, HotkeyMap):
        raise TypeError(
            "apply_remap: user_map must be HotkeyMap; got "
            f"{type(user_map).__name__}"
        )
    return default_map.merge(user_map)


# ---------------------------------------------------------------------------
# Default map — mirrors NotebookHotkeys DEFAULT_HOTKEYS
# ---------------------------------------------------------------------------


def default_hotkey_map() -> HotkeyMap:
    """Return a :class:`HotkeyMap` mirroring the notebook default table.

    Imports :mod:`pharos_editor.ui.editor.notebook_hotkeys` lazily so this
    module stays cheap to import — the notebook editor pulls in DPG
    constants which are heavier than we want in a hotkey unit test.
    """
    from pharos_editor.ui.editor.notebook_hotkeys import NotebookHotkeys
    m = HotkeyMap()
    for combo, action_id in NotebookHotkeys.BINDINGS.items():
        try:
            m.add(HotkeyBinding(
                combo=combo,
                action_id=action_id,
                source="default",
            ))
        except (ValueError, TypeError) as exc:
            _log.warning(
                "default_hotkey_map: skipping %r -> %r: %s",
                combo, action_id, exc,
            )
    return m


# ---------------------------------------------------------------------------
# HotkeyRemapWatcher — thin subclass over X6 watcher pattern
# ---------------------------------------------------------------------------


class HotkeyRemapWatcher:
    """Live-reload watcher for the user hotkey directory.

    Wraps :class:`pharos_editor.ui.user_overrides.UserOverrideLoader.watch_dir`
    so consumers get the X6 debounce + graceful watchdog-missing
    fallback, plus a strongly-typed :class:`HotkeyMap` payload on every
    debounced change.

    Parameters
    ----------
    user_dir:
        Override the discovery root. Defaults to :data:`USER_HOTKEY_DIR`.
    on_reload:
        Called with the fresh merged :class:`HotkeyMap` after every
        debounced filesystem event. Callback exceptions are logged +
        swallowed so a broken user callback never kills the watcher.
    debounce:
        Coalesce raw events within this many seconds.
    """

    def __init__(
        self,
        on_reload: Callable[[HotkeyMap], None],
        *,
        user_dir: Path | str | None = None,
        debounce: float = 0.100,
    ) -> None:
        if not callable(on_reload):
            raise TypeError(
                "HotkeyRemapWatcher: on_reload must be callable; got "
                f"{type(on_reload).__name__}"
            )
        self._on_reload = on_reload
        if user_dir is None:
            self._user_dir = USER_HOTKEY_DIR
        else:
            self._user_dir = Path(validate_path_like(
                "user_dir", "HotkeyRemapWatcher", user_dir,
            ))
        self._debounce = float(debounce)
        self._handle: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> Any:
        """Start the watcher. Returns the underlying X6 handle."""
        # Import lazily so this module never drags user_overrides (and
        # its watchdog import) into unit tests that don't need it.
        from pharos_editor.ui.user_overrides import UserOverrideLoader

        # The X6 loader watches ``root/`` recursively; we scope to the
        # hotkeys/ subdir by pointing the loader's root there.
        self._user_dir.mkdir(parents=True, exist_ok=True)
        loader = UserOverrideLoader(root=self._user_dir)

        def _cb(_kind: str, _path: Path) -> None:
            try:
                fresh = load_user_hotkeys(self._user_dir)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "HotkeyRemapWatcher: reload failed: %s", exc,
                )
                return
            try:
                self._on_reload(fresh)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "HotkeyRemapWatcher: on_reload raised: %s", exc,
                )

        self._handle = loader.watch_dir(_cb, debounce=self._debounce)
        return self._handle

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the underlying watcher (no-op when never started)."""
        h = self._handle
        if h is None:
            return
        stop = getattr(h, "stop", None)
        if callable(stop):
            try:
                stop(timeout=timeout)
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "HotkeyRemapWatcher.stop: underlying stop raised: %s",
                    exc,
                )
        self._handle = None

    def is_running(self) -> bool:
        """Return ``True`` while the underlying watcher is alive."""
        h = self._handle
        if h is None:
            return False
        is_running = getattr(h, "is_running", None)
        if not callable(is_running):
            return False
        try:
            return bool(is_running())
        except Exception:  # noqa: BLE001
            return False

    # -- Context-manager sugar -----------------------------------------

    def __enter__(self) -> "HotkeyRemapWatcher":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: D401,ANN001
        self.stop()


__all__ = [
    "BAKED_HOTKEY_DIR",
    "HotkeyBinding",
    "HotkeyMap",
    "HotkeyRemapWatcher",
    "USER_HOTKEY_DIR",
    "apply_remap",
    "bake_defaults",
    "default_hotkey_map",
    "load_user_hotkeys",
]
