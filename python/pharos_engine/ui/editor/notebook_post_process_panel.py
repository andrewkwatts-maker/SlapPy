"""Notebook-themed post-process chain editor.

The :class:`NotebookPostProcessPanel` exposes a :class:`PostProcessChain`
as an in-place reorderable, toggleable list of passes.  Per-row controls:

* :class:`HeartCheckbox` — flips ``pass_.enabled``.
* "[up] / [down]" sticker buttons — reorder the pass in the chain.
* "x" sticker button — removes the pass.
* Inline quick-tweak controls for the one or two parameters that matter
  most for the pass kind (e.g. Bloom intensity, TAA tight_variance_clip,
  Vignette strength).  The full parameter inspector remains the route
  for everything else.

Below the table:

* An "Add pass" :class:`StickerButton` opens a modal listing every
  available pass factory exposed by :mod:`pharos_engine.post_process`.
* A "Reset to preset" row with three sticker buttons — cinematic /
  arcade / iso-strategy — calls the matching preset chain factory and
  replaces the bound chain in-place.

Headless-safe — every DPG call is funnelled through ``_safe_dpg``.
"""
from __future__ import annotations

from typing import Any, Callable

from pharos_engine._validation import (
    validate_callable,
    validate_str,
)
from pharos_engine.ui.widgets.doodle_separator import DoodleSeparator
from pharos_engine.ui.widgets.heart_checkbox import HeartCheckbox
from pharos_engine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)
from pharos_engine.ui.widgets.sticker_button import StickerButton
from pharos_engine.ui.widgets.washi_panel import WashiPanel  # noqa: F401 — public mention


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


# Map ``label`` (the canonical pass id on ``PostProcessPass.label``) to the
# 1–2 quick-tweak params surfaced inline.  Each entry is a tuple of
# ``(param_key, display_label, kind, lo, hi)``.  ``kind`` is one of
# ``"float"`` / ``"int"``.  Passes not listed simply expose no inline
# controls — the row still renders the toggle + reorder buttons.
QUICK_TWEAK_PARAMS: dict[str, tuple[tuple[str, str, str, float, float], ...]] = {
    "bloom": (
        ("intensity", "intensity", "float", 0.0, 4.0),
        ("threshold", "threshold", "float", 0.0, 2.0),
    ),
    "vignette": (
        ("strength", "strength", "float", 0.0, 2.0),
        ("feather", "feather", "float", 0.0, 1.0),
    ),
    "tonemap": (
        ("exposure_ev", "exposure_ev", "float", -3.0, 3.0),
        ("saturation", "saturation", "float", 0.0, 2.0),
    ),
    "outline": (
        ("threshold", "threshold", "float", 0.0, 1.0),
        ("softness", "softness", "float", 0.0, 0.2),
    ),
    "chromatic_aberration": (
        ("strength", "strength", "float", 0.0, 0.05),
    ),
    "night_vision": (
        ("gain", "gain", "float", 0.5, 6.0),
        ("grain_strength", "grain", "float", 0.0, 0.3),
    ),
    "dof": (
        ("focal_distance", "focal_distance", "float", 0.0, 1.0),
        ("focal_range", "focal_range", "float", 0.05, 1.0),
    ),
    "blur": (
        ("radius", "radius", "int", 1, 16),
    ),
    "pixelate": (
        ("block_size", "block_size", "int", 1, 32),
    ),
    "gravity_warp": (
        ("strength", "strength", "float", 0.0, 4.0),
    ),
}


# Factories exposed in the "Add pass" modal — name to a zero-arg builder
# that returns a fresh :class:`PostProcessPass`.  Each factory delegates to
# the matching helper on :class:`PostProcessChain` (a throwaway chain is
# spun up just to mint the pass object).
def _make_factory(method_name: str) -> Callable[[], Any]:
    def _factory() -> Any:
        from pharos_engine.post_process.chain import PostProcessChain
        scratch = PostProcessChain()
        return getattr(scratch, method_name)()
    return _factory


AVAILABLE_PASSES: dict[str, Callable[[], Any]] = {
    "bloom":               _make_factory("add_bloom"),
    "tonemap":             _make_factory("add_tonemap"),
    "vignette":            _make_factory("add_vignette"),
    "outline":             _make_factory("add_outline"),
    "blur":                _make_factory("add_blur"),
    "pixelate":            _make_factory("add_pixelate"),
    "chromatic_aberration": _make_factory("add_chromatic_aberration"),
    "gravity_warp":        _make_factory("add_gravity_warp"),
    "night_vision":        _make_factory("add_night_vision"),
}


PRESET_NAMES: tuple[str, ...] = ("cinematic", "arcade", "iso_strategy")


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------


class NotebookPostProcessPanel:
    """Reorderable / toggleable editor for a :class:`PostProcessChain`.

    Parameters
    ----------
    chain:
        Initial :class:`PostProcessChain` to edit.  ``None`` builds a
        fresh empty chain so the panel is always usable.
    on_chain_changed:
        Optional callback fired whenever the chain mutates
        (add / remove / reorder / preset swap).  Receives the chain.
    """

    TITLE = "Post-Process Chain"
    MIN_WIDTH: int = 320
    MIN_HEIGHT: int = 280

    _ROOT_TAG = "notebook_pp_root"
    _ROWS_TAG = "notebook_pp_rows"
    _MODAL_TAG = "notebook_pp_modal"
    _STATUS_TAG = "notebook_pp_status"

    def __init__(
        self,
        chain: Any | None = None,
        *,
        on_chain_changed: Callable[[Any], None] | None = None,
    ) -> None:
        if chain is None:
            from pharos_engine.post_process.chain import PostProcessChain
            chain = PostProcessChain()
        self._chain = chain
        if on_chain_changed is not None:
            self._on_chain_changed = validate_callable(
                "on_chain_changed", "NotebookPostProcessPanel", on_chain_changed,
            )
        else:
            self._on_chain_changed = None
        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._modal_open: bool = False
        self._theme = resolve_theme()
        self.call_log: list[tuple[str, Any]] = []

        register_theme_listener(self._on_theme_changed)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def chain(self) -> Any:
        return self._chain

    @property
    def passes(self) -> list[Any]:
        """Return the chain's underlying pass list (including disabled)."""
        return list(self._chain._passes)

    # ------------------------------------------------------------------
    # Theme listener
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()
        self.call_log.append(("theme_changed", None))
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public actions
    # ------------------------------------------------------------------

    def set_chain(self, chain: Any) -> None:
        """Bind a new :class:`PostProcessChain` and re-render."""
        if chain is None:
            raise TypeError(
                "NotebookPostProcessPanel.set_chain: chain must not be None",
            )
        self._chain = chain
        self.call_log.append(("set_chain", None))
        if self._on_chain_changed:
            try:
                self._on_chain_changed(chain)
            except Exception:
                pass
        if self._built:
            self.refresh()

    def toggle_pass(self, label: str) -> bool:
        """Flip ``enabled`` on the pass matching *label*.  Returns new state."""
        validate_str("label", "NotebookPostProcessPanel.toggle_pass",
                     label, allow_empty=False)
        for p in self._chain._passes:
            if p.label == label:
                p.enabled = not p.enabled
                self.call_log.append(("toggle", (label, p.enabled)))
                self._notify_chain_changed()
                if self._built:
                    self.refresh()
                return p.enabled
        raise KeyError(
            f"NotebookPostProcessPanel.toggle_pass: no pass with label {label!r}",
        )

    def move_pass(self, label: str, direction: int) -> None:
        """Move the pass with *label* by *direction* (+1 down, -1 up)."""
        validate_str("label", "NotebookPostProcessPanel.move_pass",
                     label, allow_empty=False)
        passes = self._chain._passes
        for i, p in enumerate(passes):
            if p.label == label:
                target = i + direction
                if 0 <= target < len(passes):
                    passes[i], passes[target] = passes[target], passes[i]
                    self.call_log.append(("move", (label, direction)))
                    self._notify_chain_changed()
                    if self._built:
                        self.refresh()
                return
        raise KeyError(
            f"NotebookPostProcessPanel.move_pass: no pass with label {label!r}",
        )

    def remove_pass(self, label: str) -> None:
        """Drop the pass with *label* from the chain."""
        validate_str("label", "NotebookPostProcessPanel.remove_pass",
                     label, allow_empty=False)
        before = len(self._chain._passes)
        self._chain.remove(label)
        if len(self._chain._passes) == before:
            raise KeyError(
                f"NotebookPostProcessPanel.remove_pass: no pass with label {label!r}",
            )
        self.call_log.append(("remove", label))
        self._notify_chain_changed()
        if self._built:
            self.refresh()

    def add_pass(self, name: str) -> Any:
        """Append a fresh pass matching the factory *name*."""
        validate_str("name", "NotebookPostProcessPanel.add_pass",
                     name, allow_empty=False)
        factory = AVAILABLE_PASSES.get(name)
        if factory is None:
            raise KeyError(
                f"NotebookPostProcessPanel.add_pass: unknown pass {name!r}; "
                f"available: {sorted(AVAILABLE_PASSES)}",
            )
        pass_obj = factory()
        # ``factory`` minted the pass on a scratch chain — append to ours.
        self._chain.add(pass_obj)
        self.call_log.append(("add", name))
        self._notify_chain_changed()
        if self._built:
            self.refresh()
        return pass_obj

    def apply_preset(self, name: str) -> Any:
        """Replace the current chain with one of the preset factories."""
        validate_str("name", "NotebookPostProcessPanel.apply_preset",
                     name, allow_empty=False)
        if name not in PRESET_NAMES:
            raise KeyError(
                f"NotebookPostProcessPanel.apply_preset: unknown preset {name!r}; "
                f"known: {PRESET_NAMES}",
            )
        from pharos_engine.post_process import (
            arcade_chain,
            cinematic_chain,
            iso_strategy_chain,
        )
        factory = {
            "cinematic":    cinematic_chain,
            "arcade":       arcade_chain,
            "iso_strategy": iso_strategy_chain,
        }[name]
        new_chain = factory()
        self._chain = new_chain
        self.call_log.append(("preset", name))
        self._notify_chain_changed()
        if self._built:
            self.refresh()
        return new_chain

    def set_param(self, label: str, key: str, value: Any) -> None:
        """Mutate a single quick-tweak parameter on the pass *label*."""
        validate_str("label", "NotebookPostProcessPanel.set_param",
                     label, allow_empty=False)
        validate_str("key", "NotebookPostProcessPanel.set_param",
                     key, allow_empty=False)
        for p in self._chain._passes:
            if p.label == label:
                p.params[key] = value
                self.call_log.append(("param", (label, key, value)))
                self._notify_chain_changed()
                return
        raise KeyError(
            f"NotebookPostProcessPanel.set_param: no pass with label {label!r}",
        )

    # ------------------------------------------------------------------
    # Build / refresh / destroy
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        dpg = _safe_dpg()
        self._parent_tag = parent_tag
        if dpg is None:
            self._built = True
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        washi = list(self._theme.color("washi", (180, 200, 230, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                try:
                    dpg.add_text(self.TITLE, color=ink)
                except Exception:
                    pass
                try:
                    dpg.add_text("~~~~~~~~~~~~~~~~~~", color=washi)
                except Exception:
                    pass
                # Preset row.
                try:
                    with dpg.group(horizontal=True):
                        for name in PRESET_NAMES:
                            try:
                                StickerButton(
                                    label=name,
                                    sticker_icon="butterfly",
                                    callback=self._make_preset_callback(name),
                                ).build(self._ROOT_TAG)
                            except Exception:
                                pass
                except Exception:
                    pass

                # Add-pass entry-point.
                try:
                    StickerButton(
                        label="+ Add pass",
                        sticker_icon="fox",
                        callback=self._on_open_add_modal,
                    ).build(self._ROOT_TAG)
                except Exception:
                    pass

                try:
                    DoodleSeparator("wavy").build(self._ROOT_TAG)
                except Exception:
                    pass

                # Status.
                try:
                    dpg.add_text(self._format_status(), tag=self._STATUS_TAG,
                                 color=accent)
                except Exception:
                    pass

                # Pass rows.
                try:
                    with dpg.group(tag=self._ROWS_TAG):
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
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._STATUS_TAG):
                try:
                    dpg.set_value(self._STATUS_TAG, self._format_status())
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._ROWS_TAG):
                for child in list(dpg.get_item_children(self._ROWS_TAG, slot=1) or []):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._ROWS_TAG):
                    self._build_rows()
        except Exception:
            try:
                self._build_rows()
            except Exception:
                pass

    def destroy(self) -> None:
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._built = False

    # ------------------------------------------------------------------
    # Row rendering
    # ------------------------------------------------------------------

    def _build_rows(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        passes = self._chain._passes
        if not passes:
            try:
                dpg.add_text("(empty chain - add a pass to start)")
            except Exception:
                pass
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        for i, p in enumerate(passes):
            try:
                with dpg.group(horizontal=True):
                    # Enabled toggle.
                    try:
                        HeartCheckbox(
                            label=p.label or "?",
                            value=bool(p.enabled),
                            callback=self._make_toggle_callback(p.label),
                        ).build(self._ROWS_TAG)
                    except Exception:
                        try:
                            dpg.add_text(p.label, color=ink)
                        except Exception:
                            pass

                    # Reorder controls.
                    try:
                        dpg.add_button(
                            label="up",
                            callback=self._make_move_callback(p.label, -1),
                            enabled=(i > 0),
                        )
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="down",
                            callback=self._make_move_callback(p.label, +1),
                            enabled=(i < len(passes) - 1),
                        )
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="x",
                            callback=self._make_remove_callback(p.label),
                        )
                    except Exception:
                        pass

                # Quick-tweak row.
                tweaks = QUICK_TWEAK_PARAMS.get(p.label, ())
                if tweaks:
                    try:
                        with dpg.group(horizontal=True):
                            for key, label, kind, lo, hi in tweaks:
                                current = p.params.get(key, lo)
                                try:
                                    if kind == "float":
                                        dpg.add_slider_float(
                                            label=label,
                                            default_value=float(current),
                                            min_value=float(lo),
                                            max_value=float(hi),
                                            callback=self._make_param_callback(
                                                p.label, key, kind,
                                            ),
                                            width=120,
                                        )
                                    else:
                                        dpg.add_slider_int(
                                            label=label,
                                            default_value=int(current),
                                            min_value=int(lo),
                                            max_value=int(hi),
                                            callback=self._make_param_callback(
                                                p.label, key, kind,
                                            ),
                                            width=120,
                                        )
                                except Exception:
                                    pass
                    except Exception:
                        pass
            except Exception:
                try:
                    dpg.add_text(p.label or "?")
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Modal
    # ------------------------------------------------------------------

    def _on_open_add_modal(self, *_a: Any, **_kw: Any) -> None:
        """Open the modal that lists available pass factories."""
        self._modal_open = True
        self.call_log.append(("open_modal", None))
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._MODAL_TAG):
                try:
                    dpg.delete_item(self._MODAL_TAG)
                except Exception:
                    pass
            with dpg.window(label="Add pass", tag=self._MODAL_TAG, modal=True):
                for name in AVAILABLE_PASSES:
                    try:
                        dpg.add_button(
                            label=name,
                            callback=self._make_add_callback(name),
                        )
                    except Exception:
                        pass
                try:
                    dpg.add_button(label="Cancel", callback=self._close_modal)
                except Exception:
                    pass
        except Exception:
            pass

    def _close_modal(self, *_a: Any, **_kw: Any) -> None:
        self._modal_open = False
        self.call_log.append(("close_modal", None))
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._MODAL_TAG):
                dpg.delete_item(self._MODAL_TAG)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Callback factories
    # ------------------------------------------------------------------

    def _make_toggle_callback(self, label: str) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.toggle_pass(label)
            except KeyError:
                pass
        return _cb

    def _make_move_callback(
        self, label: str, direction: int,
    ) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.move_pass(label, direction)
            except KeyError:
                pass
        return _cb

    def _make_remove_callback(self, label: str) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.remove_pass(label)
            except KeyError:
                pass
        return _cb

    def _make_add_callback(self, name: str) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.add_pass(name)
            finally:
                self._close_modal()
        return _cb

    def _make_preset_callback(self, name: str) -> Callable[..., None]:
        def _cb(*_a: Any, **_kw: Any) -> None:
            try:
                self.apply_preset(name)
            except KeyError:
                pass
        return _cb

    def _make_param_callback(
        self, label: str, key: str, kind: str,
    ) -> Callable[..., None]:
        def _cb(sender: Any, app_data: Any, user_data: Any) -> None:
            if kind == "float":
                try:
                    value = float(app_data)
                except (TypeError, ValueError):
                    return
            else:
                try:
                    value = int(app_data)
                except (TypeError, ValueError):
                    return
            try:
                self.set_param(label, key, value)
            except KeyError:
                pass
        return _cb

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _format_status(self) -> str:
        passes = self._chain._passes
        enabled = sum(1 for p in passes if p.enabled)
        return f"passes: {len(passes)} | enabled: {enabled}"

    def _notify_chain_changed(self) -> None:
        if self._on_chain_changed is None:
            return
        try:
            self._on_chain_changed(self._chain)
        except Exception:
            pass


__all__ = [
    "AVAILABLE_PASSES",
    "NotebookPostProcessPanel",
    "PRESET_NAMES",
    "QUICK_TWEAK_PARAMS",
]
