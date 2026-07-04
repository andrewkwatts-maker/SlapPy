"""Notebook-themed content browser — the "table of contents" panel.

The :class:`NotebookContentBrowser` walks a project root directory and
groups the discovered files into three notebook sections:

* **Scenes** — every ``*.scene.yaml`` file under the root.
* **Scripts** — every ``*.py`` file under the root.
* **Assets** — everything else worth showing (images, audio, …).

Each section header is rendered as a strip of "washi tape", and rows are
notebook table-of-contents entries (a small SVG icon + the filename).
Clicking a row routes to the appropriate editor:

* Scene file → ``on_open_scene(path)``  (the editor binds this to
  :meth:`Engine.load_scene` or equivalent).
* Script file → ``on_open_script(path)``  (binds to
  :meth:`NotebookCodePanel.load_script`).
* Asset file → ``on_open_asset(path)`` (opens a preview popup).

Folders expand/collapse in-place.  A search box at the top filters rows
by filename substring.  A polling tick (see :meth:`refresh`) lets the
browser pick up files added externally; if ``watchdog`` is importable
the consumer can wire its observer instead — the module never imports
``watchdog`` at module level.

Headless / soft-import contract
-------------------------------

The module never imports ``dearpygui`` at module level — every
``dpg.*`` call is funneled through :func:`_safe_dpg` and wrapped in
``try/except`` so the panel can be constructed and exercised in
headless tests (the row-data layer is queryable without DPG).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable

from slappyengine._validation import (
    validate_callable,
    validate_path_like,
    validate_str,
)

if TYPE_CHECKING:  # pragma: no cover — type hints only
    from slappyengine.projects.project import Project
from slappyengine.ui.theme.svg_icon import SVGIcon
from slappyengine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)
from slappyengine.ui.widgets.sticker_corner import (
    add_sticker_corner,
    remove_sticker_corner,
)


# ---------------------------------------------------------------------------
# Section descriptors — controls bucket assignment + display order.
# ---------------------------------------------------------------------------

SECTION_SCENES = "Scenes"
SECTION_SCRIPTS = "Scripts"
SECTION_ASSETS = "Assets"

# File-extension → section map. ".scene.yaml" is a composite check so it
# is handled specially below (classify_file).
_IMAGE_EXTS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".svg"})
_AUDIO_EXTS: frozenset[str] = frozenset({".wav", ".mp3", ".ogg"})


def classify_file(path: Path) -> str | None:
    """Return one of ``SECTION_*`` strings — or ``None`` to skip the file.

    Hidden files (leading ``.``), ``__pycache__`` files, and ``*.pyc``
    bytecode are skipped.  Everything else routes to one of the three
    buckets; unknown extensions land in *Assets*.
    """
    name = path.name
    if name.startswith("."):
        return None
    if name.endswith(".pyc"):
        return None
    if "__pycache__" in path.parts:
        return None
    if name.endswith(".scene.yaml"):
        return SECTION_SCENES
    suffix = path.suffix.lower()
    if suffix == ".py":
        return SECTION_SCRIPTS
    if suffix in _IMAGE_EXTS or suffix in _AUDIO_EXTS:
        return SECTION_ASSETS
    # Everything else (markdown, json, glb, …) still belongs to assets.
    return SECTION_ASSETS


# ---------------------------------------------------------------------------
# Project asset-tree kinds — a wider, Nova3D-style classification used by
# :meth:`NotebookContentBrowser.set_project`. Distinct from the coarse
# ``SECTION_*`` buckets so scenes can subdivide into ``.scene.yaml`` vs
# ``.scene.json``, shaders (``.wgsl`` / ``.glsl``) surface as their own
# group, and materials get first-class placement.
# ---------------------------------------------------------------------------

ASSET_KIND_SCRIPT = "script"
ASSET_KIND_SCENE = "scene"
ASSET_KIND_TEXTURE = "texture"
ASSET_KIND_MATERIAL = "material"
ASSET_KIND_SHADER = "shader"
ASSET_KIND_OTHER = "other"

#: Display-order for the project asset tree. Mirrors Nova3D's content
#: browser grouping so users switching between the two feel at home.
ASSET_KIND_ORDER: tuple[str, ...] = (
    ASSET_KIND_SCRIPT,
    ASSET_KIND_SCENE,
    ASSET_KIND_TEXTURE,
    ASSET_KIND_MATERIAL,
    ASSET_KIND_SHADER,
    ASSET_KIND_OTHER,
)

#: Display labels for each kind — used by ``_render_group`` and the
#: DPG collapsing-header widget. Keeps the pluralisation consistent
#: across the panel + test assertions.
ASSET_GROUP_LABELS: dict[str, str] = {
    ASSET_KIND_SCRIPT:   "Scripts",
    ASSET_KIND_SCENE:    "Scenes",
    ASSET_KIND_TEXTURE:  "Textures",
    ASSET_KIND_MATERIAL: "Materials",
    ASSET_KIND_SHADER:   "Shaders",
    ASSET_KIND_OTHER:    "Other",
}

_TEXTURE_EXTS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_SHADER_EXTS:  frozenset[str] = frozenset({".wgsl", ".glsl"})


def classify_asset(path: Path) -> str | None:
    """Return the :data:`ASSET_KIND_*` string for *path* (or ``None``).

    Hidden files, ``__pycache__`` bytecode and ``*.pyc`` are skipped
    (returns ``None``). All other files land in one of the six kinds
    listed in :data:`ASSET_KIND_ORDER` — this is the classifier used by
    the project asset-tree renderer.
    """
    name = path.name
    if name.startswith("."):
        return None
    if name.endswith(".pyc"):
        return None
    if "__pycache__" in path.parts:
        return None

    # Composite (multi-suffix) extensions checked first so their coarser
    # single-suffix counterparts don't shadow them.
    lower = name.lower()
    if lower.endswith(".scene.yaml") or lower.endswith(".scene.json"):
        return ASSET_KIND_SCENE
    if lower.endswith(".mat.yaml") or lower.endswith(".material.yaml"):
        return ASSET_KIND_MATERIAL

    suffix = path.suffix.lower()
    if suffix == ".py":
        return ASSET_KIND_SCRIPT
    if suffix in _TEXTURE_EXTS:
        return ASSET_KIND_TEXTURE
    if suffix in _SHADER_EXTS:
        return ASSET_KIND_SHADER
    return ASSET_KIND_OTHER


def fuzzy_match(needle: str, haystack: str) -> bool:
    """Return ``True`` if every char of *needle* appears in *haystack* in order.

    Case-insensitive. An empty *needle* matches anything. Used by the
    search box to filter the project asset tree without dragging in a
    real fuzzy-matching library (``rapidfuzz`` etc.). Also handles the
    trivial substring case — ``"main"`` matches ``"main_menu.py"``
    directly — but falls through to per-character subsequence matching
    for less exact queries (``"mm"`` matches ``"main_menu.py"``).
    """
    if not needle:
        return True
    needle_l = needle.lower()
    haystack_l = haystack.lower()
    if needle_l in haystack_l:
        return True
    it = iter(haystack_l)
    return all(ch in it for ch in needle_l)


# ---------------------------------------------------------------------------
# File-type icon SVG library — each ≤500B, fills with currentColor when
# the theme wants to retint.  Verified by the test-suite.
# ---------------------------------------------------------------------------

_FILE_ICON_SVGS: dict[str, str] = {
    # Notebook page with a folded corner — scene files.
    "scene": (
        '<svg viewBox="0 0 16 16">'
        '<polygon points="2,1 11,1 14,4 14,15 2,15" fill="#f0e8d0" stroke="#806040" stroke-width="0.6"/>'
        '<polyline points="11,1 11,4 14,4" fill="none" stroke="#806040" stroke-width="0.6"/>'
        '<line x1="4" y1="7"  x2="12" y2="7"  stroke="#806040" stroke-width="0.5"/>'
        '<line x1="4" y1="9"  x2="12" y2="9"  stroke="#806040" stroke-width="0.5"/>'
        '<line x1="4" y1="11" x2="10" y2="11" stroke="#806040" stroke-width="0.5"/>'
        '</svg>'
    ),
    # Pencil for python scripts — diagonal pencil with rubber tip.
    "script": (
        '<svg viewBox="0 0 16 16">'
        '<polygon points="2,14 4,12 12,4 14,6 6,14" fill="#f0c050" stroke="#806020" stroke-width="0.6"/>'
        '<polygon points="12,4 14,6 14,4 13,3" fill="#e07060" stroke="#603020" stroke-width="0.4"/>'
        '<polygon points="2,14 4,12 5,15" fill="#404040"/>'
        '</svg>'
    ),
    # Diary page for .diary.py scripts — a heart-stamped notebook page.
    "diary": (
        '<svg viewBox="0 0 16 16">'
        '<polygon points="2,1 11,1 14,4 14,15 2,15" fill="#FBF7EC" stroke="#FF6FB5" stroke-width="0.6"/>'
        '<polyline points="11,1 11,4 14,4" fill="none" stroke="#FF6FB5" stroke-width="0.6"/>'
        '<path d="M8 12 L5 9 A2 2 0 0 1 8 7 A2 2 0 0 1 11 9 Z" fill="#FF6FB5"/>'
        '</svg>'
    ),
    # Paint palette for images.
    "image": (
        '<svg viewBox="0 0 16 16">'
        '<ellipse cx="8" cy="9" rx="6" ry="5" fill="#f0d8c0" stroke="#604030" stroke-width="0.5"/>'
        '<circle cx="5" cy="7" r="1.2" fill="#e07090"/>'
        '<circle cx="9" cy="5" r="1.2" fill="#70b0e0"/>'
        '<circle cx="11" cy="9" r="1.2" fill="#90c070"/>'
        '<circle cx="6" cy="11" r="1.2" fill="#f0c050"/>'
        '</svg>'
    ),
    # Music note for audio.
    "audio": (
        '<svg viewBox="0 0 16 16">'
        '<line x1="10" y1="2" x2="10" y2="12" stroke="#404060" stroke-width="1.2"/>'
        '<line x1="4"  y1="4" x2="4"  y2="13" stroke="#404060" stroke-width="1.2"/>'
        '<polyline points="4,4 10,2" fill="none" stroke="#404060" stroke-width="1.2"/>'
        '<ellipse cx="3"  cy="13" rx="2" ry="1.4" fill="#404060"/>'
        '<ellipse cx="9"  cy="12" rx="2" ry="1.4" fill="#404060"/>'
        '</svg>'
    ),
    # Folder for directories.
    "folder": (
        '<svg viewBox="0 0 16 16">'
        '<polygon points="1,4 6,4 7,5 15,5 15,13 1,13" fill="#e0c080" stroke="#604020" stroke-width="0.6"/>'
        '<line x1="1" y1="7" x2="15" y2="7" stroke="#604020" stroke-width="0.4"/>'
        '</svg>'
    ),
    # Generic page — fallback for unknown asset extensions.
    "page": (
        '<svg viewBox="0 0 16 16">'
        '<polygon points="3,1 11,1 13,3 13,15 3,15" fill="#f0f0e8" stroke="#606060" stroke-width="0.6"/>'
        '<polyline points="11,1 11,3 13,3" fill="none" stroke="#606060" stroke-width="0.6"/>'
        '</svg>'
    ),
}


def icon_for_path(path: Path) -> str:
    """Return the icon-key (one of :data:`_FILE_ICON_SVGS`) for *path*."""
    if path.is_dir():
        return "folder"
    name = path.name
    if name.endswith(".scene.yaml"):
        return "scene"
    if name.endswith(".diary.py"):
        return "diary"
    suffix = path.suffix.lower()
    if suffix == ".py":
        return "script"
    if suffix in _IMAGE_EXTS:
        return "image"
    if suffix in _AUDIO_EXTS:
        return "audio"
    return "page"


def icon_svg(kind: str) -> str:
    """Return the SVG markup for icon *kind* (falls back to ``page``)."""
    return _FILE_ICON_SVGS.get(kind, _FILE_ICON_SVGS["page"])


def make_file_icon(kind: str, size: int = 16) -> SVGIcon:
    """Construct an :class:`SVGIcon` for the named file-icon *kind*."""
    return SVGIcon(svg_xml=icon_svg(kind), size=size)


# ---------------------------------------------------------------------------
# Section "washi-tape glyphs" — ASCII stand-ins for the patterned tape
# strips drawn between sections.  Tests assert that each section header
# emits one of these strings so the visual contract is verifiable.
# ---------------------------------------------------------------------------

_WASHI_GLYPHS: dict[str, str] = {
    SECTION_SCENES:  "## ## ##",
    SECTION_SCRIPTS: "## ## ##",
    SECTION_ASSETS:  "## ## ##",
}


def washi_glyph(section: str) -> str:
    """Return the section-divider washi-tape glyph for *section*."""
    return _WASHI_GLYPHS.get(section, "== == ==")


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class NotebookContentBrowser:
    """File-tree panel themed as a project notebook's table of contents.

    Displays the project's directory tree under three section dividers:
    Scenes / Assets / Scripts. Click a file to open it in the matching
    editor: .scene.yaml → load_scene, .py → NotebookCodePanel.load_script,
    images/sounds → preview pane.

    Per Nova3D's ``build(parent_tag)`` protocol.

    Parameters
    ----------
    on_open_scene:
        Callback fired when the user clicks a ``.scene.yaml`` row.
    on_open_script:
        Callback fired when the user clicks a ``.py`` row — typically
        routed to ``NotebookCodePanel.load_script``.
    on_open_asset:
        Callback fired when the user clicks any other file.  The editor
        binds this to its preview popup.
    """

    TITLE = "Notebook"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 320
    MIN_HEIGHT: int = 180

    _SEARCH_TAG = "notebook_cb_search"
    _ROWS_GROUP = "notebook_cb_rows"
    _EMPTY_TAG = "notebook_cb_empty"
    _BREADCRUMB_TAG = "notebook_cb_breadcrumb"
    _POLL_INTERVAL_SECONDS = 5.0

    SECTION_ORDER: tuple[str, ...] = (
        SECTION_SCENES,
        SECTION_SCRIPTS,
        SECTION_ASSETS,
    )

    def __init__(
        self,
        on_open_scene: Callable[[Path], None],
        on_open_script: Callable[[Path], None],
        on_open_asset: Callable[[Path], None],
    ) -> None:
        self._on_open_scene = validate_callable(
            "on_open_scene", "NotebookContentBrowser", on_open_scene,
        )
        self._on_open_script = validate_callable(
            "on_open_script", "NotebookContentBrowser", on_open_script,
        )
        self._on_open_asset = validate_callable(
            "on_open_asset", "NotebookContentBrowser", on_open_asset,
        )

        self._root: Path | None = None
        # Current sub-directory the browser is focused on. When ``None``
        # or equal to the root, the whole project is shown; otherwise the
        # breadcrumb bar renders the ancestor chain relative to the root
        # and only files under ``_cwd`` are enumerated.
        self._cwd: Path | None = None
        self._search_text: str = ""
        self._expanded_dirs: set[Path] = set()
        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._theme = resolve_theme()
        self._sticker_handles: list[str] = []

        # Project asset-tree state — populated by :meth:`set_project`.
        # ``_project`` is kept as ``Any`` to avoid a runtime import of
        # ``slappyengine.projects.project`` (which itself pulls in a
        # slice of the ``[editor]`` extra). ``None`` means "no project
        # loaded — fall back to the plain ``_root`` walker".
        self._project: Any | None = None
        self._on_asset_selected: (
            Callable[[Path, str], None] | None
        ) = None
        # Guard flag so a reentrant ``set_on_asset_selected`` call from
        # inside a callback doesn't smash the ``_on_asset_selected``
        # slot while it's mid-dispatch. See :meth:`_dispatch_asset`.
        self._dispatching_asset: bool = False

        # Soft-import watchdog so externally-added files surface without a
        # polling restart.  Falls back to refresh()-on-tick when absent.
        self._watchdog_available: bool = _try_import_watchdog()

        register_theme_listener(self._on_theme_changed)

    # ------------------------------------------------------------------
    # Theme handling
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()
        if self._built:
            try:
                self.refresh()
            except Exception:
                # Theme switches must never crash the editor.
                pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_root(self) -> Path | None:
        """Return the project root currently displayed (or ``None``)."""
        return self._root

    def set_root(self, root: Path | str) -> None:
        """Bind *root* as the directory walked by the browser.

        Accepts ``str`` or :class:`Path`. Does not stat the path beyond
        what :meth:`iter_rows` already does — a non-existent root simply
        renders the empty state.
        """
        self._root = validate_path_like(
            "root", "NotebookContentBrowser.set_root", root,
        )
        # Reset expansion state when the root changes; the user clearly
        # wants a fresh look at a new tree.
        self._expanded_dirs.clear()
        self._cwd = None
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Project asset-tree (Nova3D-style content browser)
    # ------------------------------------------------------------------

    def set_project(self, project: "Project | None") -> None:
        """Swap the browsed root to *project*'s ``assets/`` directory.

        Passing ``None`` (or a project with no ``assets/`` directory)
        clears the tree — subsequent :meth:`iter_asset_tree` calls
        return an empty dict. The panel *does not* raise on a missing
        ``assets/`` directory; a freshly-scaffolded project is a
        common case and must not crash the editor.

        Parameters
        ----------
        project:
            An in-memory :class:`slappyengine.projects.Project` handle,
            or ``None`` to clear.
        """
        if project is None:
            self._project = None
            self._root = None
            self._cwd = None
            self._expanded_dirs.clear()
            if self._built:
                self.refresh()
            return

        # Duck-typed — the panel doesn't care what class ``project`` is
        # so long as it exposes ``.path`` (Path-like). This keeps the
        # test suite free of a hard dependency on the projects package.
        try:
            base = getattr(project, "path", None)
        except Exception:
            base = None
        if base is None:
            self._project = None
            self._root = None
        else:
            self._project = project
            assets_dir = Path(base) / "assets"
            # Fall back to the project root itself when there's no
            # ``assets/`` directory (freshly-created project, unusual
            # layout, tests, …). ``iter_asset_tree`` will short-circuit
            # to an empty result when nothing enumerates.
            self._root = assets_dir if assets_dir.exists() else Path(base)
        self._cwd = None
        self._expanded_dirs.clear()
        if self._built:
            self.refresh()

    def get_project(self) -> "Project | None":
        """Return the :class:`Project` handle bound via :meth:`set_project`."""
        return self._project

    def set_on_asset_selected(
        self, callback: Callable[[Path, str], None] | None,
    ) -> None:
        """Subscribe *callback* to asset clicks in the project tree.

        The callback receives ``(path, asset_kind)`` where ``asset_kind``
        is one of the :data:`ASSET_KIND_*` strings. Passing ``None``
        clears the subscription.

        Only one subscriber at a time — the design intent is that the
        editor shell owns the routing and forks internally to the code
        panel / scene loader / preview pop-up.
        """
        if callback is not None:
            callback = validate_callable(
                "callback",
                "NotebookContentBrowser.set_on_asset_selected",
                callback,
            )
        self._on_asset_selected = callback

    def _build_asset_tree(self, root: Path) -> dict[str, list[Path]]:
        """Walk *root* and return a ``{kind: [paths]}`` dict.

        Kinds are the :data:`ASSET_KIND_*` strings. Missing or
        unreadable *root* directories return an empty dict — callers
        should treat that as "empty project". Files are sorted within
        each group by lower-case name so the display order stays
        deterministic across Windows / POSIX filesystems (which return
        directory entries in different orders).
        """
        result: dict[str, list[Path]] = {k: [] for k in ASSET_KIND_ORDER}
        try:
            if not root.exists() or not root.is_dir():
                return result
        except OSError:
            return result
        try:
            candidates = sorted(root.rglob("*"), key=lambda p: str(p).lower())
        except (PermissionError, OSError):
            return result
        for child in candidates:
            try:
                if not child.is_file():
                    continue
            except OSError:
                # Broken symlink / disappearing file → skip cleanly.
                continue
            kind = classify_asset(child)
            if kind is None:
                continue
            result[kind].append(child)
        return result

    def iter_asset_tree(self) -> dict[str, list[Path]]:
        """Return the current project's asset tree, honouring the search box.

        The return value is the same shape as :meth:`_build_asset_tree`;
        empty groups are preserved so consumers can rely on
        :data:`ASSET_KIND_ORDER` for stable iteration.
        """
        if self._root is None:
            return {k: [] for k in ASSET_KIND_ORDER}
        tree = self._build_asset_tree(self._root)
        needle = (self._search_text or "").strip()
        if not needle:
            return tree
        filtered: dict[str, list[Path]] = {k: [] for k in ASSET_KIND_ORDER}
        for kind, files in tree.items():
            for path in files:
                if fuzzy_match(needle, path.name):
                    filtered[kind].append(path)
        return filtered

    def _render_group(
        self,
        group_name: str,
        files: Iterable[Path],
    ) -> None:
        """Render a DPG collapsing-header group of *files*.

        *group_name* should be a value from :data:`ASSET_GROUP_LABELS`;
        empty groups render nothing. Each row is a click-through button
        wired to :meth:`_dispatch_asset` — the callback receives the
        file path and matching :data:`ASSET_KIND_*` string.
        """
        dpg = _safe_dpg()
        if dpg is None:
            return
        # Normalise ``files`` first — an empty group is a no-op so we
        # don't clutter the collapsing-header stack with empty sections.
        file_list = list(files)
        if not file_list:
            return

        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        try:
            with dpg.collapsing_header(label=group_name, default_open=True):
                for path in file_list:
                    kind = classify_asset(path) or ASSET_KIND_OTHER
                    safe = str(abs(hash(str(path))))
                    row_tag = f"notebook_cb_asset_{safe}"
                    try:
                        with dpg.group(horizontal=True, tag=row_tag):
                            try:
                                dpg.add_text(
                                    self._icon_glyph(icon_for_path(path)),
                                    color=accent,
                                )
                            except Exception:
                                pass
                            try:
                                dpg.add_button(
                                    label=path.name,
                                    callback=self._make_asset_callback(
                                        path, kind,
                                    ),
                                    width=-1,
                                    height=18,
                                )
                            except Exception:
                                pass
                        # Right-click context menu, per the U7 spec.
                        self._attach_context_menu(row_tag, path)
                    except Exception:
                        try:
                            dpg.add_text(path.name, color=ink)
                        except Exception:
                            pass
        except Exception:
            # Stub-DPG without ``collapsing_header`` → flat fallback.
            try:
                dpg.add_text(group_name, color=ink)
            except Exception:
                pass
            for path in file_list:
                try:
                    dpg.add_text(path.name, color=ink)
                except Exception:
                    pass

    def _make_asset_callback(
        self, path: Path, kind: str,
    ) -> Callable[..., None]:
        """Build a per-row DPG callback for the project asset tree."""
        def _cb(*_args: Any, **_kwargs: Any) -> None:
            self._dispatch_asset(path, kind)
        return _cb

    def _dispatch_asset(self, path: Path, kind: str) -> None:
        """Route an asset-tree click to :attr:`_on_asset_selected`.

        Guarded with ``_dispatching_asset`` so a subscriber that calls
        :meth:`set_on_asset_selected` from inside its own callback
        cannot corrupt mid-dispatch state. Exceptions inside the
        subscriber are swallowed — the editor must never crash because
        a listener throws.
        """
        cb = self._on_asset_selected
        if cb is None:
            return
        self._dispatching_asset = True
        try:
            cb(path, kind)
        except Exception:
            pass
        finally:
            self._dispatching_asset = False

    def _attach_context_menu(self, row_tag: str, path: Path) -> None:
        """Register a right-click popup for *row_tag* (best-effort).

        Menu items: Open · Reveal in Explorer · Copy Path · Delete
        (with a confirm modal). All operations are wrapped in
        try/except so a missing DPG method drops the menu quietly
        rather than surfacing an editor-breaking traceback.
        """
        dpg = _safe_dpg()
        if dpg is None:
            return
        popup_tag = f"{row_tag}_ctx"
        try:
            with dpg.popup(row_tag, mousebutton=1, tag=popup_tag):  # type: ignore[attr-defined]
                dpg.add_button(
                    label="Open",
                    callback=lambda *_: self._context_open(path),
                )
                dpg.add_button(
                    label="Reveal in Explorer",
                    callback=lambda *_: self.reveal(path),
                )
                dpg.add_button(
                    label="Copy Path",
                    callback=lambda *_: self.copy_path(path),
                )
                dpg.add_button(
                    label="Delete",
                    callback=lambda *_: self._context_delete(path),
                )
        except Exception:
            # No popup support in the stub → silently drop the menu.
            pass

    def _context_open(self, path: Path) -> None:
        """Handle the context-menu ``Open`` action."""
        kind = classify_asset(path) or ASSET_KIND_OTHER
        self._dispatch_asset(path, kind)

    def _context_delete(self, path: Path) -> None:
        """Confirm + delete via the context menu."""
        dpg = _safe_dpg()
        if dpg is None:
            # Headless — no confirm modal, just delete silently.
            try:
                self.delete(path)
            except Exception:
                pass
            return
        modal_tag = f"notebook_cb_confirm_{abs(hash(str(path)))}"
        try:
            with dpg.window(  # type: ignore[attr-defined]
                label="Delete asset?",
                modal=True,
                tag=modal_tag,
                no_close=False,
            ):
                dpg.add_text(f"Delete {path.name}?")
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Delete",
                        callback=lambda *_: self._confirm_delete(path, modal_tag),
                    )
                    dpg.add_button(
                        label="Cancel",
                        callback=lambda *_: (
                            dpg.delete_item(modal_tag)  # type: ignore[attr-defined]
                            if dpg.does_item_exist(modal_tag) else None
                        ),
                    )
        except Exception:
            # Fallback — best-effort direct delete.
            try:
                self.delete(path)
            except Exception:
                pass

    def _confirm_delete(self, path: Path, modal_tag: str) -> None:
        """Execute the confirmed delete + tear down the modal."""
        dpg = _safe_dpg()
        try:
            self.delete(path)
        except Exception:
            pass
        if dpg is not None:
            try:
                if dpg.does_item_exist(modal_tag):
                    dpg.delete_item(modal_tag)
            except Exception:
                pass

    def copy_path(self, path: Path) -> str:
        """Copy *path*'s string form to the OS clipboard.

        Returns the string that was placed on the clipboard so callers
        (and tests) can verify without poking at platform APIs. Falls
        back silently on systems without a working clipboard.
        """
        text = str(path)
        # Try DPG first, then pyperclip, then tkinter — each block is
        # wrapped so a missing dep never becomes an editor crash.
        dpg = _safe_dpg()
        if dpg is not None:
            try:
                dpg.set_clipboard_text(text)  # type: ignore[attr-defined]
                return text
            except Exception:
                pass
        try:
            import pyperclip  # type: ignore[import-not-found]
            pyperclip.copy(text)
            return text
        except Exception:
            pass
        try:
            import tkinter
            r = tkinter.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(text)
            r.update()
            r.destroy()
        except Exception:
            pass
        return text

    # ------------------------------------------------------------------
    # Breadcrumb navigation
    # ------------------------------------------------------------------

    def get_cwd(self) -> Path | None:
        """Return the current sub-directory (or ``None`` when at the root)."""
        return self._cwd

    def set_cwd(self, cwd: Path | str | None) -> None:
        """Navigate into *cwd* — must be an ancestor of the root or ``None``.

        Passing ``None`` (or the root itself) clears the sub-directory
        focus so the whole project renders again. Values outside the
        root raise :class:`ValueError`.
        """
        if cwd is None:
            self._cwd = None
        else:
            path = Path(cwd)
            root = self._root
            if root is None:
                raise ValueError(
                    "NotebookContentBrowser.set_cwd: no root bound; "
                    "call set_root() first",
                )
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise ValueError(
                    "NotebookContentBrowser.set_cwd: cwd must live under "
                    f"the current root ({root}); got {path}",
                ) from exc
            self._cwd = path
        if self._built:
            self.refresh()

    def breadcrumb_segments(self) -> list[tuple[str, Path]]:
        """Return ``(label, path)`` tuples for the breadcrumb bar.

        The first segment is always the root's folder name (or
        ``"projects"`` when the root has no ``name``). Subsequent
        segments walk the :meth:`get_cwd` chain relative to the root.
        """
        segments: list[tuple[str, Path]] = []
        root = self._root
        if root is None:
            return [("projects", Path("."))]
        segments.append(("projects", root))
        segments.append((root.name or "root", root))
        cwd = self._cwd
        if cwd is not None and cwd != root:
            try:
                rel = cwd.relative_to(root)
            except ValueError:
                return segments
            cursor = root
            for part in rel.parts:
                cursor = cursor / part
                segments.append((part, cursor))
        return segments

    def navigate_to_segment(self, index: int) -> None:
        """Navigate to the breadcrumb segment at *index*.

        ``index == 0`` (or ``1`` on the root row) clears the sub-cwd.
        Other indices set the cwd to the corresponding ancestor path.
        """
        segments = self.breadcrumb_segments()
        if index < 0 or index >= len(segments):
            return
        _, path = segments[index]
        root = self._root
        if root is None:
            return
        if index <= 1 or path == root:
            self._cwd = None
        else:
            self._cwd = path
        if self._built:
            self.refresh()

    def set_search(self, text: str) -> None:
        """Filter rows whose filename contains *text* (case-insensitive)."""
        validate_str(
            "text", "NotebookContentBrowser.set_search", text, allow_empty=True,
        )
        self._search_text = text or ""
        if self._built:
            self.refresh()

    def get_search(self) -> str:
        """Return the current search-filter text."""
        return self._search_text

    def expand(self, path: Path) -> None:
        """Mark folder *path* as expanded so its children render."""
        self._expanded_dirs.add(Path(path))
        if self._built:
            self.refresh()

    def collapse(self, path: Path) -> None:
        """Mark folder *path* as collapsed so its children hide."""
        self._expanded_dirs.discard(Path(path))
        if self._built:
            self.refresh()

    # ------------------------------------------------------------------
    # Data layer — the tests reach into this without needing DPG.
    # ------------------------------------------------------------------

    def iter_files(self) -> list[Path]:
        """Walk the root (or cwd) and return every classifiable file."""
        if self._root is None:
            return []
        # When focused into a sub-directory, list from there instead.
        base = self._cwd if (self._cwd is not None) else self._root
        if not base.exists() or not base.is_dir():
            return []
        out: list[Path] = []
        try:
            for child in sorted(base.rglob("*"), key=lambda p: str(p).lower()):
                if not child.is_file():
                    continue
                if classify_file(child) is None:
                    continue
                out.append(child)
        except (PermissionError, OSError):
            return out
        return out

    def iter_rows(self) -> list[dict[str, Any]]:
        """Return the rows the renderer would draw, grouped by section.

        Each row is a dict::

            {"section": str, "path": Path, "name": str, "icon": str,
             "depth": int, "kind": "file"}

        Section dividers are returned interleaved with file rows as
        ``{"section": str, "kind": "header"}``.
        """
        files = self.iter_files()
        needle = self._search_text.strip().lower()
        if needle:
            files = [p for p in files if needle in p.name.lower()]

        if not files:
            return []

        # Group by section, preserving SECTION_ORDER.
        buckets: dict[str, list[Path]] = {s: [] for s in self.SECTION_ORDER}
        for path in files:
            section = classify_file(path)
            if section is None:
                continue
            buckets[section].append(path)

        out: list[dict[str, Any]] = []
        root = self._root
        for section in self.SECTION_ORDER:
            paths = buckets[section]
            if not paths:
                continue
            out.append({"section": section, "kind": "header"})
            for p in paths:
                try:
                    rel = p.relative_to(root) if root else p
                except ValueError:
                    rel = p
                depth = max(0, len(rel.parts) - 1)
                out.append({
                    "section": section,
                    "path":    p,
                    "name":    p.name,
                    "icon":    icon_for_path(p),
                    "depth":   depth,
                    "kind":    "file",
                })
        return out

    # ------------------------------------------------------------------
    # Build / refresh
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Render the panel under *parent_tag* (DPG collapsing header)."""
        dpg = _safe_dpg()
        self._parent_tag = parent_tag

        if dpg is None:
            self._built = True
            return

        try:
            with dpg.collapsing_header(
                label=self.TITLE, default_open=True, parent=parent_tag,
            ):
                # Breadcrumb bar — renders above the search box so the
                # user can jump back to any ancestor with one click.
                try:
                    with dpg.group(horizontal=True, tag=self._BREADCRUMB_TAG):
                        self._build_breadcrumb()
                except Exception:
                    try:
                        self._build_breadcrumb()
                    except Exception:
                        pass

                # Search box wrapped with a washi-tape underline.
                try:
                    dpg.add_input_text(
                        hint="Find a page...",
                        tag=self._SEARCH_TAG,
                        callback=self._on_search_changed,
                        width=-1,
                    )
                except Exception:
                    pass
                washi = list(self._theme.color("washi", (180, 200, 230, 255)))
                try:
                    dpg.add_text("~~~~~~~~~~~~~~~~~~", color=washi)
                except Exception:
                    pass

                try:
                    with dpg.group(tag=self._ROWS_GROUP):
                        self._build_rows()
                except Exception:
                    self._build_rows()
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

        self._built = True

    def refresh(self) -> None:
        """Rebuild the rows from the current root + filter state.

        Called automatically on theme change / search input / set_root.
        Consumers may also call it on a 5-second polling tick (see
        :data:`_POLL_INTERVAL_SECONDS`) to pick up files added by other
        tools on disk.
        """
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            exists = dpg.does_item_exist(self._ROWS_GROUP)
        except Exception:
            exists = False
        if exists:
            try:
                for child in dpg.get_item_children(self._ROWS_GROUP, slot=1):
                    dpg.delete_item(child)
                with dpg.group(parent=self._ROWS_GROUP):
                    self._build_rows()
                return
            except Exception:
                pass
        # Stub-DPG fallback — flat call path.
        try:
            self._build_rows()
        except Exception:
            pass

    def destroy(self) -> None:
        """Detach theme listener + drop sticker decorations."""
        unregister_theme_listener(self._on_theme_changed)
        for handle in list(self._sticker_handles):
            try:
                remove_sticker_corner(handle)
            except Exception:
                pass
        self._sticker_handles.clear()
        self._built = False

    # ------------------------------------------------------------------
    # Row rendering
    # ------------------------------------------------------------------

    def _build_breadcrumb(self) -> None:
        """Render the top-of-panel breadcrumb bar.

        Each segment is a clickable button; the separators between them
        render as ``" / "`` text in the theme's ink colour.
        """
        dpg = _safe_dpg()
        if dpg is None:
            return
        segments = self.breadcrumb_segments()
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        for i, (label, _path) in enumerate(segments):
            if i > 0:
                try:
                    dpg.add_text(" / ", color=ink)
                except Exception:
                    pass
            try:
                dpg.add_button(
                    label=label,
                    small=True,
                    callback=(
                        lambda s, a, u, idx=i: self.navigate_to_segment(idx)
                    ),
                )
            except Exception:
                # Stub-DPG without ``small`` → fall through with plain text.
                try:
                    dpg.add_text(label, color=ink)
                except Exception:
                    pass

    def _build_rows(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return

        # Project mode: render the six-group Nova3D-style asset tree.
        if self._project is not None:
            tree = self.iter_asset_tree()
            has_any = any(tree.values())
            if not has_any:
                self._build_empty_state()
                return
            for kind in ASSET_KIND_ORDER:
                files = tree.get(kind, [])
                if not files:
                    continue
                self._render_group(ASSET_GROUP_LABELS[kind], files)
            return

        # Legacy mode — driven by :meth:`set_root` (no project bound).
        rows = self.iter_rows()
        if not rows:
            self._build_empty_state()
            return

        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        washi = list(self._theme.color("washi", (180, 200, 230, 255)))
        secondary = list(self._theme.color(
            "text_secondary",
            self._theme.color("ink", (115, 115, 122, 220)),
        ))

        for row in rows:
            if row["kind"] == "header":
                self._build_section_header(row["section"], washi, secondary)
            else:
                self._build_file_row(row, accent, ink)

    def _build_section_header(
        self, section: str, washi: list[int], secondary: list[int],
    ) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            dpg.add_text(washi_glyph(section), color=washi)
        except Exception:
            pass
        try:
            dpg.add_text(section, color=secondary)
        except Exception:
            pass

    def _build_file_row(
        self, row: dict[str, Any], accent: list[int], ink: list[int],
    ) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        path = row["path"]
        depth = row["depth"]
        name = row["name"]
        icon_kind = row["icon"]
        section = row["section"]

        safe = str(abs(hash(str(path))))
        row_tag = f"notebook_cb_row_{safe}"

        try:
            with dpg.group(horizontal=True, tag=row_tag):
                if depth > 0:
                    try:
                        dpg.add_text(" " * (depth * 2))
                    except Exception:
                        pass
                try:
                    dpg.add_text(self._icon_glyph(icon_kind), color=accent)
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label=name,
                        callback=self._make_open_callback(section, path),
                        width=-1,
                        height=18,
                    )
                except Exception:
                    pass
        except Exception:
            # Stub-DPG fallback.
            try:
                dpg.add_text(name, color=ink, parent=self._parent_tag)
            except Exception:
                pass

    def _build_empty_state(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        try:
            dpg.add_text(
                "Project is empty - drop a creature into the scene to start",
                color=ink,
                tag=self._EMPTY_TAG,
            )
        except Exception:
            try:
                dpg.add_text(
                    "Project is empty - drop a creature into the scene to start",
                )
            except Exception:
                pass
        # Small fox sticker corner — pinned to the empty-state area.
        try:
            handle = add_sticker_corner(self._EMPTY_TAG, "fox", "BR")
            self._sticker_handles.append(handle)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_search_changed(self, sender: Any, app_data: Any, user_data: Any) -> None:
        self._search_text = str(app_data or "")
        self.refresh()

    def _make_open_callback(
        self, section: str, path: Path,
    ) -> Callable[..., None]:
        """Build a per-row DPG callback that routes the click."""
        def _cb(*_args: Any, **_kwargs: Any) -> None:
            self._dispatch_open(section, path)
        return _cb

    def _dispatch_open(self, section: str, path: Path) -> None:
        """Route a click to the matching open-callback."""
        try:
            if section == SECTION_SCENES:
                self._on_open_scene(path)
            elif section == SECTION_SCRIPTS:
                self._on_open_script(path)
            else:
                self._on_open_asset(path)
        except Exception:
            # Callbacks must never crash the editor.
            pass

    # ------------------------------------------------------------------
    # Context-menu actions
    # ------------------------------------------------------------------

    def rename(self, path: Path, new_name: str) -> Path:
        """Rename *path* to *new_name* (kept inside the same parent).

        Returns the new :class:`Path`.  Refuses paths outside the root
        and refuses names that resolve outside the parent directory.
        """
        path = Path(path)
        new_name = validate_str(
            "new_name", "NotebookContentBrowser.rename",
            new_name, allow_empty=False,
        )
        target = path.parent / new_name
        if target.parent.resolve() != path.parent.resolve():
            raise ValueError(
                "rename: new_name must not escape the parent directory",
            )
        path.rename(target)
        if self._built:
            self.refresh()
        return target

    def delete(self, path: Path) -> None:
        """Delete *path* (file or empty directory)."""
        path = Path(path)
        if path.is_dir():
            path.rmdir()
        else:
            path.unlink()
        if self._built:
            self.refresh()

    def duplicate(self, path: Path) -> Path:
        """Duplicate *path* alongside itself with a ``_copy`` suffix."""
        import shutil
        path = Path(path)
        stem = path.stem
        suffix = path.suffix
        # Multi-suffix (.scene.yaml) handling.
        if path.name.endswith(".scene.yaml"):
            stem = path.name[:-len(".scene.yaml")]
            suffix = ".scene.yaml"
        idx = 1
        while True:
            cand = path.parent / f"{stem}_copy{('' if idx == 1 else str(idx))}{suffix}"
            if not cand.exists():
                break
            idx += 1
        if path.is_dir():
            shutil.copytree(path, cand)
        else:
            shutil.copy2(path, cand)
        if self._built:
            self.refresh()
        return cand

    def reveal(self, path: Path) -> None:
        """Open the OS file explorer at *path*'s parent (best-effort)."""
        path = Path(path)
        target = str(path if path.is_dir() else path.parent)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", target])  # noqa: S603,S607
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])  # noqa: S603,S607
            else:
                subprocess.Popen(["xdg-open", target])  # noqa: S603,S607
        except Exception:
            # No usable file manager — silently no-op.
            pass

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _icon_glyph(kind: str) -> str:
        """ASCII-ish stand-in for the SVG icon — used by the DPG text path."""
        return {
            "scene":  "<>",
            "script": "/",
            "diary":  "<3",
            "image":  "[]",
            "audio":  "o)",
            "folder": "[+]",
            "page":   "-",
        }.get(kind, "-")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


def _try_import_watchdog() -> bool:
    """Return ``True`` if ``watchdog`` is importable (soft, optional dep)."""
    try:
        import watchdog  # type: ignore[import-not-found] # noqa: F401
        return True
    except Exception:
        return False


__all__ = [
    "ASSET_GROUP_LABELS",
    "ASSET_KIND_MATERIAL",
    "ASSET_KIND_ORDER",
    "ASSET_KIND_OTHER",
    "ASSET_KIND_SCENE",
    "ASSET_KIND_SCRIPT",
    "ASSET_KIND_SHADER",
    "ASSET_KIND_TEXTURE",
    "NotebookContentBrowser",
    "SECTION_ASSETS",
    "SECTION_SCENES",
    "SECTION_SCRIPTS",
    "classify_asset",
    "classify_file",
    "fuzzy_match",
    "icon_for_path",
    "icon_svg",
    "make_file_icon",
    "washi_glyph",
]
