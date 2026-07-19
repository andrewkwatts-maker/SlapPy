"""``AssetImportPanel`` — CCC3: drag-drop import panel with thumbnail cards.

Presented as a new bottom-area tab in the editor shell. Provides:

* a "Drop files here" hero area (visual only — the drop wiring is
  provided by whatever OS bridge the shell exposes; the panel exposes
  :meth:`on_paths_dropped` so the shell / tests can push paths in);
* an "Import…" fallback button that mimics a file dialog by pushing a
  provided path list through :meth:`on_paths_dropped`;
* a grid of thumbnail cards — one per imported asset — with a small
  right-click context menu offering *Add to Scene*, *Copy path*,
  *Remove*.

The panel dispatches through
:func:`slappyengine.asset_import.type_router.import_by_extension` and
registers each successful import with the shared
:class:`slappyengine.assets.database.AssetDatabase`.

Headless / soft-import contract
-------------------------------

* ``dearpygui`` is only imported inside ``_safe_dpg`` — so the panel
  builds cleanly under CI test stubs and even when DPG is absent
  altogether.
* Every ``dpg.*`` call is wrapped in ``try / except`` so a stub that
  raises ``NotImplementedError`` on a widget the panel didn't test
  against never surfaces as a build error.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from slappyengine.asset_import.type_router import (
    THUMBNAIL_SIZE,
    ImportRouteResult,
    import_by_extension,
    supported_extensions,
)

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Type badge palette — a short human-friendly label per route ``kind``.
# ---------------------------------------------------------------------------

_TYPE_BADGES: dict[str, str] = {
    "texture":           "TEX",
    "hdr_texture":       "HDR",
    "cubemap":           "CUBE",
    "shader":            "WGSL",
    "mesh":              "MESH",
    "scene":             "GLTF",
    "material":          "MAT",
    "material_library":  "MTL",
    "prefab":            "PREFAB",
    "scene_yaml":        "SCENE",
    "yaml":              "YAML",
    "script":            "PY",
    "unsupported":       "?",
    "error":             "ERR",
}


def type_badge(kind: str) -> str:
    """Return the short badge string for a route kind."""
    return _TYPE_BADGES.get(kind, kind.upper()[:6])


# ---------------------------------------------------------------------------
# Card metadata.
# ---------------------------------------------------------------------------


@dataclass
class ImportedAssetCard:
    """One imported asset displayed in the panel grid."""

    card_id: str
    kind: str
    path: Path
    handle: Any
    thumbnail: np.ndarray
    dpg_texture_tag: str = ""
    dpg_card_tag: str = ""
    dpg_popup_tag: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Safe DPG accessor — mirrors the pattern used by other notebook panels.
# ---------------------------------------------------------------------------


def _safe_dpg():
    try:
        import dearpygui.dearpygui as dpg  # noqa: PLC0415
    except Exception:
        return None
    return dpg


# ---------------------------------------------------------------------------
# The panel.
# ---------------------------------------------------------------------------


class AssetImportPanel:
    """Editor panel that surfaces the CCC3 asset drop workflow.

    Parameters
    ----------
    asset_database:
        Optional :class:`AssetDatabase` instance. Defaults to the shared
        singleton (``AssetDatabase.instance()``) on first import. Tests
        pass a fresh instance to avoid cross-test bleed.
    on_add_to_scene:
        Optional callback ``(ImportedAssetCard) -> None`` fired from the
        right-click *Add to Scene* menu.
    router:
        Import router callable. Defaults to
        :func:`import_by_extension` — tests override with a fake to
        avoid touching the disk-backed importers.
    """

    TITLE = "Asset Import"
    ROOT_PREFIX = "asset_import_panel"

    def __init__(
        self,
        *,
        asset_database: Any = None,
        on_add_to_scene: Callable[[ImportedAssetCard], None] | None = None,
        router: Callable[[str | Path], ImportRouteResult] = import_by_extension,
    ) -> None:
        self._db = asset_database
        self._on_add_to_scene = on_add_to_scene
        self._router = router
        self._instance_id = uuid.uuid4().hex[:8]
        self._panel_tag = f"{self.ROOT_PREFIX}_root_{self._instance_id}"
        self._drop_zone_tag = f"{self.ROOT_PREFIX}_dropzone_{self._instance_id}"
        self._grid_tag = f"{self.ROOT_PREFIX}_grid_{self._instance_id}"
        self._status_tag = f"{self.ROOT_PREFIX}_status_{self._instance_id}"
        self._texture_registry_tag = f"{self.ROOT_PREFIX}_texreg_{self._instance_id}"
        self._parent_tag: str | None = None
        self._built: bool = False

        self._cards: list[ImportedAssetCard] = []
        self._card_index: dict[str, ImportedAssetCard] = {}

    # ------------------------------------------------------------------
    # Public introspection surface — used by tests + the editor shell.
    # ------------------------------------------------------------------

    @property
    def cards(self) -> list[ImportedAssetCard]:
        """Snapshot of the currently-displayed cards."""
        return list(self._cards)

    def get_supported_extensions(self) -> tuple[str, ...]:
        return supported_extensions()

    # ------------------------------------------------------------------
    # Build — materialise the DPG layout.
    # ------------------------------------------------------------------

    def build(self, parent_tag: str) -> None:
        """Materialise the panel under ``parent_tag``.

        Safe to call without DPG installed — all widget calls funnel
        through :func:`_safe_dpg` and swallow failures silently so the
        panel is testable in headless CI.
        """
        self._parent_tag = parent_tag
        dpg = _safe_dpg()
        if dpg is None:
            self._built = True
            return

        # Texture registry (needed to display any dynamic thumbnails).
        try:
            if not dpg.does_item_exist(self._texture_registry_tag):
                dpg.add_texture_registry(tag=self._texture_registry_tag)
        except Exception:
            pass

        try:
            with dpg.child_window(
                tag=self._panel_tag,
                parent=parent_tag,
                border=False,
                autosize_x=True,
                autosize_y=True,
            ):
                self._build_dropzone(dpg)
                self._build_toolbar(dpg)
                self._build_status(dpg)
                self._build_grid(dpg)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("AssetImportPanel.build failed: %s", exc)
        self._built = True

    def _build_dropzone(self, dpg) -> None:
        try:
            with dpg.child_window(
                tag=self._drop_zone_tag,
                parent=self._panel_tag,
                border=True,
                height=96,
                autosize_x=True,
            ):
                dpg.add_text("Drop files here")
                dpg.add_text(
                    f"Supported: {', '.join(self.get_supported_extensions())}",
                )
        except Exception:
            pass

    def _build_toolbar(self, dpg) -> None:
        try:
            with dpg.group(horizontal=True, parent=self._panel_tag):
                dpg.add_button(
                    label="Import…",
                    tag=f"{self.ROOT_PREFIX}_import_btn_{self._instance_id}",
                    callback=lambda *_: self._open_file_dialog(),
                )
                dpg.add_button(
                    label="Clear",
                    tag=f"{self.ROOT_PREFIX}_clear_btn_{self._instance_id}",
                    callback=lambda *_: self.clear(),
                )
        except Exception:
            pass

    def _build_status(self, dpg) -> None:
        try:
            dpg.add_text(
                "",
                tag=self._status_tag,
                parent=self._panel_tag,
            )
        except Exception:
            pass

    def _build_grid(self, dpg) -> None:
        try:
            with dpg.child_window(
                tag=self._grid_tag,
                parent=self._panel_tag,
                autosize_x=True,
                autosize_y=True,
                border=False,
            ):
                pass
        except Exception:
            pass

    # ------------------------------------------------------------------
    # File dialog fallback — surfaces a DPG file_dialog when possible.
    # ------------------------------------------------------------------

    def _open_file_dialog(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            dialog_tag = f"{self.ROOT_PREFIX}_dlg_{self._instance_id}"
            if dpg.does_item_exist(dialog_tag):
                dpg.delete_item(dialog_tag)
            with dpg.file_dialog(
                tag=dialog_tag,
                directory_selector=False,
                show=True,
                modal=True,
                callback=self._on_dialog_selected,
                width=600,
                height=400,
            ):
                # Extension filters mirror the router's supported set.
                for ext in self.get_supported_extensions():
                    dpg.add_file_extension(ext, color=(200, 180, 100, 255))
                dpg.add_file_extension(".*")
        except Exception as exc:  # noqa: BLE001
            _LOG.info("file_dialog fallback: %s", exc)

    def _on_dialog_selected(self, sender: Any, app_data: Any) -> None:
        selections = []
        if isinstance(app_data, dict):
            sel = app_data.get("selections") or {}
            selections = list(sel.values())
        elif isinstance(app_data, (list, tuple)):
            selections = list(app_data)
        elif isinstance(app_data, str):
            selections = [app_data]
        if selections:
            self.on_paths_dropped(selections)

    # ------------------------------------------------------------------
    # Drop entry point — routes files through the type router and
    # produces thumbnail cards.
    # ------------------------------------------------------------------

    def on_paths_dropped(self, paths: Iterable[str | Path]) -> list[ImportedAssetCard]:
        """Import each of *paths* and produce a card per result.

        Returns the list of cards created (successful or errored). Cards
        are appended to :attr:`cards` and rendered into the grid on the
        next DPG frame.
        """
        added: list[ImportedAssetCard] = []
        for raw in paths:
            path = Path(raw)
            try:
                result = self._router(path)
            except Exception as exc:  # noqa: BLE001
                # Router is designed never to raise; but be defensive.
                _LOG.warning("Router raised on %s: %s", path, exc)
                result = ImportRouteResult(
                    kind="error", handle=None, path=path,
                    thumbnail=self._fallback_thumbnail(),
                    error=str(exc),
                )
            card = self._make_card(result)
            self._cards.append(card)
            self._card_index[card.card_id] = card
            added.append(card)
            self._maybe_register_in_database(card)
            self._render_card(card)
        self._set_status(
            f"Imported {sum(1 for c in added if c.kind not in ('unsupported', 'error'))} of {len(added)} file(s)."
        )
        return added

    # Alias — the shell / DPG file_dialog callback may hand us a batch
    # via the plural verb.
    def import_paths(self, paths: Iterable[str | Path]) -> list[ImportedAssetCard]:
        return self.on_paths_dropped(paths)

    def import_path(self, path: str | Path) -> ImportedAssetCard:
        return self.on_paths_dropped([path])[0]

    # ------------------------------------------------------------------
    # Card management + DPG rendering.
    # ------------------------------------------------------------------

    def _make_card(self, result: ImportRouteResult) -> ImportedAssetCard:
        cid = f"card_{len(self._cards)}_{uuid.uuid4().hex[:6]}"
        thumb = result.thumbnail
        if thumb is None or thumb.shape != (THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4):
            thumb = self._fallback_thumbnail()
        card = ImportedAssetCard(
            card_id=cid,
            kind=result.kind,
            path=result.path,
            handle=result.handle,
            thumbnail=thumb,
            dpg_texture_tag=f"{self.ROOT_PREFIX}_tex_{cid}",
            dpg_card_tag=f"{self.ROOT_PREFIX}_card_{cid}",
            dpg_popup_tag=f"{self.ROOT_PREFIX}_pop_{cid}",
            error=result.error,
        )
        return card

    def _fallback_thumbnail(self) -> np.ndarray:
        return np.full((THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4), 200, dtype=np.uint8)

    def _render_card(self, card: ImportedAssetCard) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            # Register the dynamic texture — DPG wants a float32 flat
            # array in [0, 1]. Convert on the fly and pin it into the
            # texture registry.
            flat = (card.thumbnail.astype(np.float32) / 255.0).ravel().tolist()
            if not dpg.does_item_exist(card.dpg_texture_tag):
                dpg.add_static_texture(
                    THUMBNAIL_SIZE,
                    THUMBNAIL_SIZE,
                    flat,
                    tag=card.dpg_texture_tag,
                    parent=self._texture_registry_tag,
                )
        except Exception:
            pass

        try:
            with dpg.child_window(
                tag=card.dpg_card_tag,
                parent=self._grid_tag,
                width=THUMBNAIL_SIZE + 32,
                height=THUMBNAIL_SIZE + 64,
                border=True,
            ):
                try:
                    dpg.add_image(card.dpg_texture_tag)
                except Exception:
                    pass
                dpg.add_text(card.path.name)
                dpg.add_text(f"[{type_badge(card.kind)}]")
                dpg.add_button(
                    label="Remove",
                    callback=lambda *_: self.remove_card(card.card_id),
                )
        except Exception:
            pass

        # Right-click popup — Add to Scene / Copy path / Remove.
        try:
            with dpg.popup(card.dpg_card_tag, tag=card.dpg_popup_tag):
                dpg.add_menu_item(
                    label="Add to Scene",
                    callback=lambda *_: self._add_to_scene(card),
                )
                dpg.add_menu_item(
                    label="Copy path",
                    callback=lambda *_: self._copy_path(card),
                )
                dpg.add_menu_item(
                    label="Remove",
                    callback=lambda *_: self.remove_card(card.card_id),
                )
        except Exception:
            pass

    def _add_to_scene(self, card: ImportedAssetCard) -> None:
        if self._on_add_to_scene is not None:
            try:
                self._on_add_to_scene(card)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("on_add_to_scene raised: %s", exc)

    def _copy_path(self, card: ImportedAssetCard) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            dpg.set_clipboard_text(str(card.path))
        except Exception:
            pass

    def remove_card(self, card_id: str) -> bool:
        card = self._card_index.pop(card_id, None)
        if card is None:
            return False
        self._cards = [c for c in self._cards if c.card_id != card_id]
        dpg = _safe_dpg()
        if dpg is not None:
            for tag in (card.dpg_card_tag, card.dpg_texture_tag, card.dpg_popup_tag):
                try:
                    if dpg.does_item_exist(tag):
                        dpg.delete_item(tag)
                except Exception:
                    pass
        return True

    def clear(self) -> None:
        for cid in list(self._card_index.keys()):
            self.remove_card(cid)
        self._set_status("Cleared.")

    def _set_status(self, message: str) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._status_tag):
                dpg.set_value(self._status_tag, message)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # AssetDatabase integration — silently soft-fails when the DB isn't
    # available (e.g. running in an isolated test harness).
    # ------------------------------------------------------------------

    def _maybe_register_in_database(self, card: ImportedAssetCard) -> None:
        if card.kind in ("unsupported", "error"):
            return
        db = self._db
        if db is None:
            try:
                from slappyengine.assets.database import AssetDatabase  # noqa: PLC0415
                db = AssetDatabase.instance()
                self._db = db
            except Exception:
                return
        if db is None:
            return
        # We register a bespoke handler that just returns our already-loaded
        # handle — the router already paid the import cost, no need to
        # redo it inside AssetDatabase.
        try:
            abs_path = str(card.path.resolve())
            # If the extension already has a handler, we don't override —
            # AssetDatabase.load() will use it and cache the record. Just
            # trigger the load so a record appears in the registry.
            ext = card.path.suffix.lower()
            handlers = getattr(db, "_handlers", {})
            if ext not in handlers:
                # Register a lightweight handler that returns our handle.
                handle = card.handle

                def _loader(_p: str, _h=handle) -> Any:
                    return _h

                try:
                    db.register_handler(ext, _loader)
                except Exception:
                    pass
            if card.path.exists():
                try:
                    db.load(abs_path)
                except Exception as exc:  # noqa: BLE001
                    _LOG.debug("AssetDatabase.load skipped %s: %s", abs_path, exc)
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("AssetDatabase integration skipped: %s", exc)


__all__ = [
    "AssetImportPanel",
    "ImportedAssetCard",
    "type_badge",
]
