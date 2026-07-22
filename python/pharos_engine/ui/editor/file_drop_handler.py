"""``FileDropHandler`` — OS drag-and-drop routing for the editor viewport.

When a user drags files from Explorer / Finder onto the editor
viewport, the target action depends on the file kind:

* ``*.prefab.yaml``  → spawn as a prefab at the drop position.
* ``*.theme.yaml`` / ``*.theme.css`` → install into the user theme store.
* ``*.wgsl`` / ``*.glsl`` → copy to ``~/.pharos_engine/ui/shaders/``.
* ``*.png`` / ``*.jpg`` / ``*.webp`` → copy into the project's
  ``assets/textures/`` folder.
* ``*.py`` → attach as a script to the currently-selected entity.
* Everything else → :attr:`DropAction.REJECTED` with a human-readable
  ``reason`` string.

The module is deliberately pure-Python, framework-agnostic, and
side-effect free: DPG never touches it. The editor shell wires
:meth:`FileDropHandler.on_file_drop` into whatever OS drop callback
DPG (or the wider host app) exposes, and the handler classifies +
dispatches without any coupling to the UI toolkit.

Design provenance
-----------------

* Task **EE4** — Drag-and-drop file importer (2026-07-04 sprint).
* Companion of :mod:`pharos_engine.ui.editor.notebook_prefab_menu` —
  same PrefabLibrary integration point, but sourced from an OS drop
  instead of a clicked card.
* Style / patterns: dataclass event + enum action + registered
  callback (mirrors :mod:`pharos_engine.ui.editor.notebook_command_palette`).
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable

from pharos_engine._validation import (
    validate_callable,
    validate_finite_2tuple,
)

if TYPE_CHECKING:  # pragma: no cover
    from pharos_engine.dynamics import World
    from pharos_engine.prefabs import PrefabLibrary
    from pharos_engine.ui.theme.user_themes import UserThemeStore

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extension → action mapping (public — introspectable by tools + tests).
# ---------------------------------------------------------------------------


#: Multi-suffix (``.prefab.yaml`` style) → action mapping. Checked first
#: because ``.yaml`` alone would otherwise swallow ``.prefab.yaml``.
COMPOUND_SUFFIX_MAP: dict[str, "DropAction"] = {}

#: Single-suffix (``.png`` style) → action mapping.
SINGLE_SUFFIX_MAP: dict[str, "DropAction"] = {}


# ---------------------------------------------------------------------------
# Enums + dataclasses
# ---------------------------------------------------------------------------


class DropAction(Enum):
    """The routing verdict for a single dropped file."""

    PREFAB_SPAWN = "prefab_spawn"
    THEME_INSTALL = "theme_install"
    SHADER_INSTALL = "shader_install"
    IMAGE_IMPORT = "image_import"
    SCRIPT_ATTACH = "script_attach"
    REJECTED = "rejected"


# Populate the maps now that ``DropAction`` exists.
COMPOUND_SUFFIX_MAP.update(
    {
        ".prefab.yaml": DropAction.PREFAB_SPAWN,
        ".theme.yaml": DropAction.THEME_INSTALL,
        ".theme.css": DropAction.THEME_INSTALL,
    }
)
SINGLE_SUFFIX_MAP.update(
    {
        ".wgsl": DropAction.SHADER_INSTALL,
        ".glsl": DropAction.SHADER_INSTALL,
        ".png": DropAction.IMAGE_IMPORT,
        ".jpg": DropAction.IMAGE_IMPORT,
        ".jpeg": DropAction.IMAGE_IMPORT,
        ".webp": DropAction.IMAGE_IMPORT,
        ".py": DropAction.SCRIPT_ATTACH,
    }
)


@dataclass(frozen=True)
class FileDropEvent:
    """Immutable snapshot of an OS drop event.

    Attributes
    ----------
    paths:
        Every file the user dropped. Order is significant: the batch
        is dispatched in list order so callers can rely on it (for e.g.
        stacking spawns in Z-order).
    drop_position:
        World-space coordinates of the drop in the editor viewport.
        Forwarded to :meth:`PrefabLibrary.spawn` for PREFAB_SPAWN
        actions; ignored by the other actions.
    modifier_keys:
        Names of the modifiers held during the drop
        (``"shift"``, ``"ctrl"``, ``"alt"``, ``"cmd"``). Empty when
        no modifiers were down. Consumers use this for e.g.
        shift-drop = "replace" vs. plain drop = "add".
    """

    paths: list[Path]
    drop_position: tuple[float, float]
    modifier_keys: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        # ``frozen=True`` blocks ``self.x = ...`` after ``__init__``; use
        # ``object.__setattr__`` for the coercions below.
        coerced_paths = [Path(p) for p in self.paths]
        object.__setattr__(self, "paths", coerced_paths)
        validate_finite_2tuple(
            "drop_position", "FileDropEvent", self.drop_position,
        )
        object.__setattr__(
            self, "drop_position", (
                float(self.drop_position[0]),
                float(self.drop_position[1]),
            ),
        )
        object.__setattr__(
            self, "modifier_keys", {str(m).lower() for m in self.modifier_keys},
        )


@dataclass(frozen=True)
class DropHandlerResult:
    """Per-file outcome from :meth:`FileDropHandler.handle_drop`.

    Attributes
    ----------
    action:
        The :class:`DropAction` chosen by :meth:`FileDropHandler.classify`.
    path:
        The file the result applies to.
    success:
        ``True`` iff the registered handler ran without raising *and*
        the action was not REJECTED.
    error:
        Human-readable error / reject reason. Empty string on success.
    """

    action: DropAction
    path: Path
    success: bool
    error: str = ""


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


HandlerCallback = Callable[[Path, "FileDropEvent", Any], None]


class FileDropHandler:
    """Classifies dropped files and dispatches them to registered handlers.

    Handlers are plain callables — ``(path, event, ctx) -> None``. The
    handler receives the specific file it should process (not the whole
    batch) so a one-file / many-file drop uses the same signature.

    ``ctx`` is opaque — supply whatever container is convenient
    (typically an editor-shell reference, a ``SimpleNamespace``, or a
    dict). :func:`default_handlers` demonstrates the pattern by pulling
    ``ctx.prefab_library`` / ``ctx.world`` / ``ctx.user_theme_store`` /
    ``ctx.project_root`` / ``ctx.selected_entity`` / ``ctx.toast`` out
    on demand.

    Parameters
    ----------
    handlers:
        Optional ``{DropAction: callback}`` seed map. Additional
        handlers can be added at any time with
        :meth:`register_handler`.
    """

    def __init__(
        self,
        *,
        handlers: dict[DropAction, HandlerCallback] | None = None,
    ) -> None:
        self._handlers: dict[DropAction, HandlerCallback] = {}
        if handlers:
            for action, cb in handlers.items():
                self.register_handler(action, cb)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    @staticmethod
    def classify(path: Path | str) -> DropAction:
        """Return the :class:`DropAction` for *path* based on its suffix.

        Compound suffixes (``.prefab.yaml``) win over their tail-only
        counterparts (``.yaml``). The lookup is case-insensitive on the
        suffix so drops from Windows Explorer (uppercase extensions)
        route the same as drops from macOS.
        """
        if path is None:
            return DropAction.REJECTED
        p = Path(path) if not isinstance(path, Path) else path
        name = p.name.lower()
        for suffix, action in COMPOUND_SUFFIX_MAP.items():
            if name.endswith(suffix):
                return action
        single = p.suffix.lower()
        return SINGLE_SUFFIX_MAP.get(single, DropAction.REJECTED)

    @staticmethod
    def reject_reason(path: Path | str) -> str:
        """Human-readable "why was this rejected?" string."""
        try:
            p = Path(path)
        except TypeError:
            return "unsupported path (not path-like)"
        suffix = p.suffix.lower() or "<no extension>"
        return (
            f"unsupported file type {suffix!r}: {p.name} — expected one of "
            f"{sorted(set(COMPOUND_SUFFIX_MAP) | set(SINGLE_SUFFIX_MAP))}"
        )

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def register_handler(
        self,
        action: DropAction,
        callback: HandlerCallback,
    ) -> None:
        """Register a *callback* for one :class:`DropAction`.

        Later registrations replace earlier ones for the same action —
        callers who want a chain-of-responsibility should stack the
        callbacks themselves.
        """
        if not isinstance(action, DropAction):
            raise TypeError(
                f"FileDropHandler.register_handler: action must be a "
                f"DropAction; got {type(action).__name__}"
            )
        if action is DropAction.REJECTED:
            raise ValueError(
                "FileDropHandler.register_handler: cannot register a "
                "handler for DropAction.REJECTED (rejection is terminal)"
            )
        validate_callable(
            "callback", "FileDropHandler.register_handler", callback,
        )
        self._handlers[action] = callback

    def has_handler(self, action: DropAction) -> bool:
        """Return ``True`` when a handler is registered for *action*."""
        return action in self._handlers

    def registered_actions(self) -> set[DropAction]:
        """Snapshot of every action that currently has a handler."""
        return set(self._handlers.keys())

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def handle_drop(
        self,
        event: FileDropEvent,
        ctx: Any = None,
    ) -> list[DropHandlerResult]:
        """Dispatch every path in *event* through the registered handlers.

        A failure in one file's handler never aborts the batch — each
        file gets its own :class:`DropHandlerResult`. Exceptions from
        the callback are captured (type + message) into
        :attr:`DropHandlerResult.error` and logged at WARNING level.

        Parameters
        ----------
        event:
            The drop payload. See :class:`FileDropEvent`.
        ctx:
            Opaque context handed to every callback. Typically the
            :class:`pharos_engine.ui.editor.shell.EditorShell` instance
            (or a stand-in exposing the same attributes — see
            :func:`default_handlers`).

        Returns
        -------
        list[DropHandlerResult]
            One entry per file in ``event.paths`` — same order.
        """
        if not isinstance(event, FileDropEvent):
            raise TypeError(
                "FileDropHandler.handle_drop: event must be a FileDropEvent; "
                f"got {type(event).__name__}"
            )
        results: list[DropHandlerResult] = []
        for path in event.paths:
            action = self.classify(path)
            if action is DropAction.REJECTED:
                reason = self.reject_reason(path)
                _LOG.info(
                    "FileDropHandler: rejected drop %s (%s)", path, reason,
                )
                results.append(
                    DropHandlerResult(
                        action=DropAction.REJECTED,
                        path=path,
                        success=False,
                        error=reason,
                    )
                )
                continue
            callback = self._handlers.get(action)
            if callback is None:
                reason = (
                    f"no handler registered for {action.name} "
                    f"(file: {path.name})"
                )
                _LOG.warning("FileDropHandler: %s", reason)
                results.append(
                    DropHandlerResult(
                        action=DropAction.REJECTED,
                        path=path,
                        success=False,
                        error=reason,
                    )
                )
                continue
            try:
                callback(path, event, ctx)
            except Exception as exc:  # noqa: BLE001 — surface every failure
                _LOG.warning(
                    "FileDropHandler: handler for %s raised on %s (%s: %s)",
                    action.name, path, type(exc).__name__, exc,
                )
                results.append(
                    DropHandlerResult(
                        action=action,
                        path=path,
                        success=False,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            results.append(
                DropHandlerResult(
                    action=action,
                    path=path,
                    success=True,
                    error="",
                )
            )
        return results

    # ------------------------------------------------------------------
    # Integration entry-point
    # ------------------------------------------------------------------

    def on_file_drop(
        self,
        paths: Iterable[Path | str],
        position: tuple[float, float],
        *,
        modifiers: Iterable[str] | None = None,
        ctx: Any = None,
    ) -> list[DropHandlerResult]:
        """Adapter for OS / DPG drop callbacks.

        Wraps :meth:`handle_drop` with the "flat args" signature DPG's
        future file-drop callback is expected to use. Accepts an
        arbitrary iterable of paths and an optional modifier iterable
        so callers can pass a set, list, tuple, or generator.
        """
        path_list = [Path(p) for p in paths]
        modifier_set: set[str] = set()
        if modifiers is not None:
            modifier_set = {str(m).lower() for m in modifiers}
        event = FileDropEvent(
            paths=path_list,
            drop_position=(float(position[0]), float(position[1])),
            modifier_keys=modifier_set,
        )
        return self.handle_drop(event, ctx)


# ---------------------------------------------------------------------------
# Default handlers — wired against real engine subsystems.
# ---------------------------------------------------------------------------


#: User-writable shader directory. Public so :func:`default_handlers`
#: consumers can override it in tests without monkey-patching.
DEFAULT_SHADER_DIR: Path = Path.home() / ".pharos_engine" / "ui" / "shaders"


def _copy_into(src: Path, dest_dir: Path) -> Path:
    """Copy *src* → *dest_dir* / basename, creating parents as needed.

    Returns the destination path. Overwrites any existing file (drop-
    to-import is a user-directed action; the toast should tell them if
    they clobbered something).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copy2(src, dest)
    return dest


def _handle_prefab_spawn(path: Path, event: FileDropEvent, ctx: Any) -> None:
    library = getattr(ctx, "prefab_library", None)
    world = getattr(ctx, "world", None)
    if library is None:
        raise RuntimeError(
            "prefab_spawn handler: ctx.prefab_library is None — no library"
            " to load into"
        )
    if world is None:
        raise RuntimeError(
            "prefab_spawn handler: ctx.world is None — nowhere to spawn"
        )
    # Load the file into the library (registers by ``prefab.name``).
    text = path.read_text(encoding="utf-8")
    from pharos_engine.prefabs import Prefab  # local import — avoids cycle

    prefab = Prefab.from_yaml(text)
    library.register(prefab)
    library.spawn(prefab.name, world, event.drop_position)


def _handle_theme_install(path: Path, event: FileDropEvent, ctx: Any) -> None:
    store = getattr(ctx, "user_theme_store", None)
    if store is None:
        raise RuntimeError(
            "theme_install handler: ctx.user_theme_store is None"
        )
    user_dir: Path = getattr(store, "_user_dir", None) or (
        Path.home() / ".pharos_engine" / "themes"
    )
    _copy_into(path, user_dir)


def _handle_shader_install(path: Path, event: FileDropEvent, ctx: Any) -> None:
    shader_dir: Path = getattr(ctx, "shader_dir", None) or DEFAULT_SHADER_DIR
    _copy_into(path, shader_dir)


def _handle_image_import(path: Path, event: FileDropEvent, ctx: Any) -> None:
    project_root: Path | None = getattr(ctx, "project_root", None)
    if project_root is None:
        raise RuntimeError(
            "image_import handler: ctx.project_root is None — no project "
            "to import into"
        )
    tex_dir = Path(project_root) / "assets" / "textures"
    _copy_into(path, tex_dir)


def _handle_script_attach(path: Path, event: FileDropEvent, ctx: Any) -> None:
    selected = getattr(ctx, "selected_entity", None)
    if selected is None:
        toast = getattr(ctx, "toast", None)
        if callable(toast):
            toast(
                f"Cannot attach {path.name}: no entity is selected.",
            )
            return
        raise RuntimeError(
            "script_attach handler: ctx.selected_entity is None and "
            "ctx.toast is not callable"
        )
    # Prefer an explicit ``attach_script`` method, fall back to
    # setting ``script_path`` on the selected entity.
    attach = getattr(selected, "attach_script", None)
    if callable(attach):
        attach(path)
    else:
        try:
            setattr(selected, "script_path", Path(path))
        except AttributeError as exc:
            raise RuntimeError(
                f"script_attach handler: selected entity {selected!r} "
                f"does not accept a script attachment ({exc})"
            ) from exc


def default_handlers() -> dict[DropAction, HandlerCallback]:
    """Factory returning the canonical action → handler wiring.

    Every callback expects a ``ctx`` object exposing (any subset of):

    * ``prefab_library`` — :class:`pharos_engine.prefabs.PrefabLibrary`.
    * ``world``          — target :class:`pharos_engine.dynamics.World`.
    * ``user_theme_store`` — :class:`pharos_engine.ui.theme.user_themes.UserThemeStore`.
    * ``shader_dir``     — override for :data:`DEFAULT_SHADER_DIR` (optional).
    * ``project_root``   — root of the current project (for image imports).
    * ``selected_entity`` — currently-selected entity, or ``None``.
    * ``toast``          — ``Callable[[str], None]`` for user feedback.

    Missing attributes surface as ``RuntimeError`` at dispatch time,
    which :meth:`FileDropHandler.handle_drop` captures into the
    :class:`DropHandlerResult`. Callers are free to swap any handler
    for a custom one via :meth:`FileDropHandler.register_handler`.
    """
    return {
        DropAction.PREFAB_SPAWN: _handle_prefab_spawn,
        DropAction.THEME_INSTALL: _handle_theme_install,
        DropAction.SHADER_INSTALL: _handle_shader_install,
        DropAction.IMAGE_IMPORT: _handle_image_import,
        DropAction.SCRIPT_ATTACH: _handle_script_attach,
    }


def make_default_handler() -> FileDropHandler:
    """One-shot factory: :class:`FileDropHandler` pre-wired with defaults."""
    return FileDropHandler(handlers=default_handlers())


__all__ = [
    "DropAction",
    "FileDropEvent",
    "DropHandlerResult",
    "FileDropHandler",
    "HandlerCallback",
    "COMPOUND_SUFFIX_MAP",
    "SINGLE_SUFFIX_MAP",
    "DEFAULT_SHADER_DIR",
    "default_handlers",
    "make_default_handler",
]
