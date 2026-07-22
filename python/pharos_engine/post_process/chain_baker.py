"""Baked post-process chain presets — sprint Z3.

The :class:`ChainBaker` mirrors the
:class:`pharos_editor.ui.theme.user_themes.UserThemeStore` pattern for
post-process chain manifests: every shipping preset lives as a YAML
file under
``python/pharos_engine/post_process/baked_chains/*.chain.yaml`` inside
the wheel, and on first use a baker copies each file into
``~/.pharos_engine/postprocess_chains/`` so users can edit the YAML
freely without touching the installed package.

The user directory *wins* — :meth:`ChainBaker.load` prefers a
user-side file over the baked file when both exist. Missing baked
files are re-copied on every call to :meth:`bake_defaults` (never
overwriting existing user files) so nothing goes missing after
``pip install --upgrade``.

Six shipping presets
--------------------

* ``default``     bloom -> taa -> tonemap -> dither (matches
  :data:`pharos_engine.post_process.DEFAULT_CHAIN`).
* ``crisp``       tonemap -> dither only (no bloom / TAA — pixel-art clarity).
* ``dreamy``      heavy bloom (mip_count=8, strength=0.6) -> loose TAA
  (variance_clip_gamma=1.4) -> tonemap -> dither.
* ``neon``        bloom -> chromatic_aberration (custom) -> tonemap -> dither.
* ``retro_film``  soft bloom -> grain (custom) -> tonemap -> dither.
* ``debug``       tonemap only — isolates other subsystems.

Custom pass stubs
-----------------

The ``neon`` and ``retro_film`` presets reference two custom pass
kinds (``chromatic_aberration`` and ``grain``) that the CPU manifest
dispatcher does not know about by default. To keep the presets
loadable + dispatchable in the CPU harness without a GPU,
:meth:`ChainBaker.register_stub_handlers` seeds *pass-through* stubs
for both handlers. The stubs return the image unchanged; downstream
GPU consumers (or richer CPU implementations) may overwrite them by
calling :func:`register_pass_handler` again after
:meth:`register_stub_handlers` has run.

Two-line usage::

    baker = ChainBaker()
    baker.bake_defaults()                       # idempotent; safe on every boot
    manifest = baker.load("dreamy")             # user file preferred
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_path_like,
)

from .chain_manifest import (
    ChainManifest,
    ChainManifestError,
    PassSpec,
    register_pass_handler,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ChainBakerError(Exception):
    """Raised when a baked chain file is missing, corrupt, or malformed."""


# ---------------------------------------------------------------------------
# BakerResult
# ---------------------------------------------------------------------------


@dataclass
class BakerResult:
    """Structured result of a :meth:`ChainBaker.bake_defaults` call.

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
# Stub handlers for custom pass kinds
# ---------------------------------------------------------------------------


def _chromatic_aberration_stub(
    image: np.ndarray, spec: PassSpec, ctx: dict[str, Any],
) -> np.ndarray:
    """Pass-through stub for the ``chromatic_aberration`` custom pass.

    The real ChromaticAberration pass lives on the GPU side; the CPU
    manifest harness only needs a handler registered so
    :func:`apply_manifest` does not raise on the ``neon`` preset. Users
    may overwrite this stub by calling :func:`register_pass_handler`
    after :meth:`ChainBaker.register_stub_handlers` has run.
    """
    return np.asarray(image, dtype=np.float32).copy()


def _grain_stub(
    image: np.ndarray, spec: PassSpec, ctx: dict[str, Any],
) -> np.ndarray:
    """Pass-through stub for the ``grain`` custom pass.

    The real Grain pass lives on the GPU side; the CPU manifest harness
    only needs a handler registered so :func:`apply_manifest` does not
    raise on the ``retro_film`` preset. Users may overwrite this stub
    by calling :func:`register_pass_handler` after
    :meth:`ChainBaker.register_stub_handlers` has run.
    """
    return np.asarray(image, dtype=np.float32).copy()


# ---------------------------------------------------------------------------
# ChainBaker
# ---------------------------------------------------------------------------


class ChainBaker:
    """Baked / user directory manager for post-process chain manifests.

    Chains live in two locations:

    1. **Baked** (read-only):
       ``python/pharos_engine/post_process/baked_chains/`` — shipped
       inside the wheel; the canonical source of every shipping preset.
    2. **User** (read/write):
       ``~/.pharos_engine/postprocess_chains/`` — copied from baked on
       first launch. Users edit files here to customise the shipping
       presets without touching the installed package.

    Instances are cheap; a fresh :class:`ChainBaker` per boot is the
    intended usage.

    Parameters
    ----------
    user_dir:
        Override the default ``~/.pharos_engine/postprocess_chains/``
        location — used by tests to isolate the on-disk state per case.
    baked_dir:
        Override the packaged baked directory (also test-only;
        production code always accepts the class default).
    """

    #: User-writable directory. Users may edit any file inside.
    USER_DIR: Path = Path.home() / ".pharos_engine" / "postprocess_chains"

    #: Read-only baked directory shipped inside the wheel.
    BAKED_DIR: Path = Path(__file__).parent / "baked_chains"

    #: File-name suffix; public constant so tools can reuse it.
    SUFFIX: str = ".chain.yaml"

    def __init__(
        self,
        user_dir: Path | str | None = None,
        baked_dir: Path | str | None = None,
    ) -> None:
        if user_dir is None:
            self._user_dir = self.USER_DIR
        else:
            self._user_dir = Path(validate_path_like(
                "user_dir", "ChainBaker", user_dir,
            ))
        if baked_dir is None:
            self._baked_dir = self.BAKED_DIR
        else:
            self._baked_dir = Path(validate_path_like(
                "baked_dir", "ChainBaker", baked_dir,
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
        """Copy every baked chain into the user directory (idempotent).

        Mirrors :meth:`UserThemeStore.ensure_defaults_copied`: existing
        user files are never overwritten so hand-edits survive across
        engine upgrades. Missing baked files are re-copied on every
        call.

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
                "user_dir", "ChainBaker.bake_defaults", user_dir,
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
        """Return the sorted names of every baked chain preset."""
        return sorted(self._name_from_path(p) for p in self._iter_baked_paths())

    def list_user(self) -> list[str]:
        """Return the sorted names of every user-side preset.

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

    def load(self, name: str) -> ChainManifest:
        """Return the :class:`ChainManifest` for *name*.

        The user-side file wins; when it is missing the baked file is
        used. Raises :class:`ChainBakerError` when neither exists or
        when the on-disk YAML is malformed.
        """
        preset = validate_non_empty_str(
            "name", "ChainBaker.load", name,
        )
        user_path = self._user_path_for(preset)
        if user_path.exists():
            return self._load_yaml(user_path)
        baked_path = self._baked_path_for(preset)
        if baked_path.exists():
            return self._load_yaml(baked_path)
        raise ChainBakerError(
            f"ChainBaker.load: no chain preset named {preset!r} "
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
            "name", "ChainBaker.is_edited", name,
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

        Raises :class:`ChainBakerError` when no baked file exists for
        that name (e.g. the preset was authored by the user and never
        shipped in the wheel).
        """
        preset = validate_non_empty_str(
            "name", "ChainBaker.revert", name,
        )
        baked_path = self._baked_path_for(preset)
        if not baked_path.exists():
            raise ChainBakerError(
                f"ChainBaker.revert: no baked chain preset named "
                f"{preset!r} (looked at {baked_path})"
            )
        self._user_dir.mkdir(parents=True, exist_ok=True)
        user_path = self._user_path_for(preset)
        self._atomic_copy(baked_path, user_path)
        return user_path

    # ------------------------------------------------------------------
    # Stub handler registration
    # ------------------------------------------------------------------

    @classmethod
    def register_stub_handlers(cls) -> tuple[str, ...]:
        """Seed pass-through stubs for the custom pass kinds this baker uses.

        The ``neon`` preset references a ``chromatic_aberration``
        custom pass and the ``retro_film`` preset references a
        ``grain`` custom pass. Without registered handlers the CPU
        dispatcher (:func:`apply_manifest`) raises when it hits either
        pass. Calling this classmethod once (typically during editor /
        harness boot) makes both presets loadable and dispatchable on
        the CPU harness with pass-through semantics.

        Callers that ship real implementations may overwrite the stubs
        by calling :func:`register_pass_handler` again after this
        classmethod has run.

        Returns
        -------
        tuple[str, ...]
            The names of every stub handler registered — in stable
            order matching the baked YAML presets that need them.
        """
        register_pass_handler("chromatic_aberration", _chromatic_aberration_stub)
        register_pass_handler("grain", _grain_stub)
        return ("chromatic_aberration", "grain")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _iter_baked_paths(self) -> list[Path]:
        """Return every ``*.chain.yaml`` under :attr:`baked_dir`, sorted."""
        if not self._baked_dir.is_dir():
            return []
        return sorted(
            p for p in self._baked_dir.iterdir()
            if p.is_file() and p.name.endswith(self.SUFFIX)
        )

    def _iter_user_paths(self) -> list[Path]:
        """Return every ``*.chain.yaml`` under :attr:`user_dir`, sorted."""
        if not self._user_dir.is_dir():
            return []
        return sorted(
            p for p in self._user_dir.iterdir()
            if p.is_file() and p.name.endswith(self.SUFFIX)
        )

    def _name_from_path(self, path: Path) -> str:
        """Return the bare preset name from ``foo.chain.yaml``."""
        stem = path.name
        if stem.endswith(self.SUFFIX):
            return stem[: -len(self.SUFFIX)]
        return path.stem

    def _user_path_for(self, name: str) -> Path:
        return self._user_dir / f"{name}{self.SUFFIX}"

    def _baked_path_for(self, name: str) -> Path:
        return self._baked_dir / f"{name}{self.SUFFIX}"

    def _load_yaml(self, path: Path) -> ChainManifest:
        """Read + parse a single ``*.chain.yaml`` into a :class:`ChainManifest`."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ChainBakerError(
                f"ChainBaker: unable to read {path}: {exc}"
            ) from exc
        try:
            return ChainManifest.from_yaml(text)
        except ChainManifestError as exc:
            raise ChainBakerError(
                f"ChainBaker: corrupt chain file {path}: {exc}"
            ) from exc
        except Exception as exc:
            raise ChainBakerError(
                f"ChainBaker: unreadable chain file {path}: {exc}"
            ) from exc

    @classmethod
    def _atomic_copy(cls, source: Path, dest: Path) -> None:
        """Copy *source* -> *dest* atomically via a same-dir temp file."""
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise ChainBakerError(
                f"ChainBaker: unable to read baked chain {source}: {exc}"
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
    "ChainBaker",
    "ChainBakerError",
]
