"""Baked editor layout presets — sprint CC4.

Mirrors the :class:`slappyengine.post_process.chain_baker.ChainBaker`
pattern for editor layout snapshots: every shipping preset lives as a
YAML file under
``python/slappyengine/ui/editor/baked_layouts/*.layout.yaml`` inside
the wheel, and on first use a baker copies each file into
``~/.slappyengine/layouts/`` so users can edit the YAML freely without
touching the installed package.

The user directory *wins* — :meth:`LayoutBaker.load` prefers a
user-side file over the baked file when both exist. Missing baked
files are re-copied on every call to :meth:`bake_defaults` (never
overwriting existing user files) so nothing goes missing after
``pip install --upgrade``.

Six shipping presets
--------------------

* ``default``       standard four-pane notebook (toolbar / outliner /
  inspector / content browser) — matches
  :data:`slappyengine.ui.editor.default_layouts.DEFAULT_LAYOUT`.
* ``triple_pane``   three equal columns; content browser collapsed —
  matches :data:`TRIPLE_PANE_LAYOUT`.
* ``wide_code``     outliner / inspector squeezed to leave a wide code
  pane centre-right — matches :data:`WIDE_CODE_LAYOUT`.
* ``focus_mode``    only viewport + inspector visible; every other
  panel hidden. Ships with a ``font_size_bump: 1.2`` meta hint.
* ``debugging``     message log + inspector + telemetry stacked on the
  right; small viewport on the left.
* ``presentation``  full-screen viewport; toolbars / panels hidden;
  large status bar pinned at the top.

Two-line usage::

    baker = LayoutBaker()
    baker.bake_defaults()                       # idempotent; safe on every boot
    layout = baker.load("focus_mode")           # user file preferred
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from slappyengine._validation import (
    validate_non_empty_str,
    validate_path_like,
)

from .layout_persistence import EditorLayout, SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LayoutBakerError(Exception):
    """Raised when a baked layout file is missing, corrupt, or malformed."""


# ---------------------------------------------------------------------------
# BakerResult
# ---------------------------------------------------------------------------


@dataclass
class BakerResult:
    """Structured result of a :meth:`LayoutBaker.bake_defaults` call.

    Parameters
    ----------
    user_dir
        The resolved user directory (created if missing).
    written
        Paths freshly copied from the baked directory during this call.
        Empty when every user file was already present.
    skipped
        Names of presets that already existed on the user side and were
        therefore left untouched. Preserves user edits.
    baked_names
        The full ordered list of baked preset names — handy for menus
        that want to display "shipping" vs "custom" partitions.
    """

    user_dir: Path
    written: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    baked_names: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LayoutBaker
# ---------------------------------------------------------------------------


class LayoutBaker:
    """Baked / user directory manager for editor layout presets.

    Layouts live in two locations:

    1. **Baked** (read-only):
       ``python/slappyengine/ui/editor/baked_layouts/`` — shipped
       inside the wheel; the canonical source of every shipping preset.
    2. **User** (read/write):
       ``~/.slappyengine/layouts/`` — copied from baked on first
       launch. Users edit files here to customise the shipping presets
       without touching the installed package.

    Instances are cheap; a fresh :class:`LayoutBaker` per boot is the
    intended usage.

    Parameters
    ----------
    user_dir:
        Override the default ``~/.slappyengine/layouts/`` location —
        used by tests to isolate the on-disk state per case.
    baked_dir:
        Override the packaged baked directory (also test-only;
        production code always accepts the class default).
    """

    #: User-writable directory. Users may edit any file inside.
    USER_DIR: Path = Path.home() / ".slappyengine" / "layouts"

    #: Read-only baked directory shipped inside the wheel.
    BAKED_DIR: Path = Path(__file__).parent / "baked_layouts"

    #: File-name suffix; public constant so tools can reuse it.
    SUFFIX: str = ".layout.yaml"

    def __init__(
        self,
        user_dir: Path | str | None = None,
        baked_dir: Path | str | None = None,
    ) -> None:
        if user_dir is None:
            self._user_dir = self.USER_DIR
        else:
            self._user_dir = Path(validate_path_like(
                "user_dir", "LayoutBaker", user_dir,
            ))
        if baked_dir is None:
            self._baked_dir = self.BAKED_DIR
        else:
            self._baked_dir = Path(validate_path_like(
                "baked_dir", "LayoutBaker", baked_dir,
            ))

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def user_dir(self) -> Path:
        """Return the resolved user directory."""
        return self._user_dir

    @property
    def baked_dir(self) -> Path:
        """Return the resolved baked directory."""
        return self._baked_dir

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def bake_defaults(
        self, user_dir: Path | str | None = None,
    ) -> BakerResult:
        """Copy every baked layout into the user directory (idempotent).

        Mirrors :meth:`ChainBaker.bake_defaults`: existing user files
        are never overwritten so hand-edits survive across engine
        upgrades. Missing baked files are re-copied on every call.

        Parameters
        ----------
        user_dir:
            One-off override of the instance's :attr:`user_dir`. When
            supplied, the copy targets that directory instead. The
            instance's stored directory is *not* mutated.

        Returns
        -------
        BakerResult
            Structured summary of the operation. ``written`` lists the
            new files; ``skipped`` lists the presets left intact.
        """
        if user_dir is None:
            target = self._user_dir
        else:
            target = Path(validate_path_like(
                "user_dir", "LayoutBaker.bake_defaults", user_dir,
            ))

        baked_paths = self._iter_baked_paths()
        baked_names = [self._name_from_path(p) for p in baked_paths]

        target.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        skipped: list[str] = []
        for src in baked_paths:
            dest = target / src.name
            name = self._name_from_path(src)
            if dest.exists():
                skipped.append(name)
                continue
            self._atomic_copy(src, dest)
            written.append(dest)
        return BakerResult(
            user_dir=target,
            written=written,
            skipped=skipped,
            baked_names=baked_names,
        )

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_baked(self) -> list[str]:
        """Return the sorted names of every baked layout preset."""
        return sorted(self._name_from_path(p) for p in self._iter_baked_paths())

    def list_user(self) -> list[str]:
        """Return the sorted names of every user-side layout preset.

        Empty list when :attr:`user_dir` does not exist (pre-first-
        launch state — caller should follow up with
        :meth:`bake_defaults`).
        """
        if not self._user_dir.is_dir():
            return []
        return sorted(
            self._name_from_path(p) for p in self._iter_user_paths()
        )

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, name: str) -> EditorLayout:
        """Return the :class:`EditorLayout` for *name*.

        The user-side file wins; when it is missing the baked file is
        used. Raises :class:`LayoutBakerError` when neither exists or
        when the on-disk YAML is malformed / carries an unknown schema
        version.
        """
        preset = validate_non_empty_str(
            "name", "LayoutBaker.load", name,
        )
        user_path = self._user_path_for(preset)
        if user_path.exists():
            return self._load_yaml(user_path)
        baked_path = self._baked_path_for(preset)
        if baked_path.exists():
            return self._load_yaml(baked_path)
        raise LayoutBakerError(
            f"LayoutBaker.load: no layout preset named {preset!r} "
            f"(searched {user_path} and {baked_path})"
        )

    # ------------------------------------------------------------------
    # Edit detection + revert
    # ------------------------------------------------------------------

    def is_edited(self, name: str) -> bool:
        """Return ``True`` when the user file differs from the baked file.

        Byte-for-byte comparison — whitespace-only edits register as
        edited. Returns ``False`` when the user file is missing (the
        baked file is the effective content) or when the baked file is
        missing (a user-authored preset has no baseline).
        """
        preset = validate_non_empty_str(
            "name", "LayoutBaker.is_edited", name,
        )
        user_path = self._user_path_for(preset)
        baked_path = self._baked_path_for(preset)
        if not user_path.exists() or not baked_path.exists():
            return False
        try:
            user_bytes = user_path.read_bytes()
            baked_bytes = baked_path.read_bytes()
        except OSError:
            return False
        return user_bytes != baked_bytes

    def revert(self, name: str) -> Path:
        """Overwrite the user file for *name* with the baked version.

        Raises :class:`LayoutBakerError` when no baked file exists for
        that name (e.g. the preset was authored by the user and never
        shipped in the wheel).
        """
        preset = validate_non_empty_str(
            "name", "LayoutBaker.revert", name,
        )
        baked_path = self._baked_path_for(preset)
        if not baked_path.exists():
            raise LayoutBakerError(
                f"LayoutBaker.revert: no baked layout preset named "
                f"{preset!r} (looked at {baked_path})"
            )
        self._user_dir.mkdir(parents=True, exist_ok=True)
        user_path = self._user_path_for(preset)
        self._atomic_copy(baked_path, user_path)
        return user_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _iter_baked_paths(self) -> list[Path]:
        """Return every ``*.layout.yaml`` under :attr:`baked_dir`, sorted."""
        if not self._baked_dir.is_dir():
            return []
        return sorted(
            p for p in self._baked_dir.iterdir()
            if p.is_file() and p.name.endswith(self.SUFFIX)
        )

    def _iter_user_paths(self) -> list[Path]:
        """Return every ``*.layout.yaml`` under :attr:`user_dir`, sorted."""
        if not self._user_dir.is_dir():
            return []
        return sorted(
            p for p in self._user_dir.iterdir()
            if p.is_file() and p.name.endswith(self.SUFFIX)
        )

    def _name_from_path(self, path: Path) -> str:
        """Return the bare preset name from ``foo.layout.yaml``."""
        stem = path.name
        if stem.endswith(self.SUFFIX):
            return stem[: -len(self.SUFFIX)]
        return path.stem

    def _user_path_for(self, name: str) -> Path:
        return self._user_dir / f"{name}{self.SUFFIX}"

    def _baked_path_for(self, name: str) -> Path:
        return self._baked_dir / f"{name}{self.SUFFIX}"

    def _load_yaml(self, path: Path) -> EditorLayout:
        """Read + parse a single ``*.layout.yaml`` into an :class:`EditorLayout`.

        Preserves any ``meta`` block (e.g. ``font_size_bump``) as a
        transient attribute on the returned :class:`EditorLayout` so
        callers that care about layout meta-hints (focus mode, etc.)
        can inspect it via ``getattr(layout, "meta", {})`` without
        forcing every ``EditorLayout`` construction site through a new
        constructor argument.
        """
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise LayoutBakerError(
                f"LayoutBaker: unable to read {path}: {exc}"
            ) from exc
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise LayoutBakerError(
                f"LayoutBaker: corrupt layout file {path}: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise LayoutBakerError(
                f"LayoutBaker: top-level of {path} must be a mapping; "
                f"got {type(data).__name__}"
            )
        # Schema gate — matches the LayoutPersistence.load contract.
        schema = int(data.get("schema_version", 0))
        if schema != SCHEMA_VERSION:
            raise LayoutBakerError(
                f"LayoutBaker: {path} uses schema {schema}, expected "
                f"{SCHEMA_VERSION}"
            )
        # Pull an optional ``meta`` block off so the EditorLayout
        # constructor (which doesn't know about meta) doesn't reject it.
        meta = data.pop("meta", None)
        try:
            layout = EditorLayout.from_dict(data)
        except (TypeError, ValueError, KeyError) as exc:
            raise LayoutBakerError(
                f"LayoutBaker: malformed layout {path}: {exc}"
            ) from exc
        if isinstance(meta, dict):
            # Attach as a transient attribute — dataclass forbids new
            # slots but allows dynamic attrs on the instance.
            try:
                object.__setattr__(layout, "meta", dict(meta))
            except Exception:
                pass
        return layout

    @classmethod
    def _atomic_copy(cls, source: Path, dest: Path) -> None:
        """Copy *source* -> *dest* atomically via a same-dir temp file."""
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise LayoutBakerError(
                f"LayoutBaker: unable to read baked layout {source}: {exc}"
            ) from exc
        cls._atomic_write_text(dest, text)

    @staticmethod
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
                    # fsync is best-effort on some networked filesystems.
                    pass
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


__all__ = [
    "BakerResult",
    "LayoutBaker",
    "LayoutBakerError",
]
