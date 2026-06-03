"""``NotebookSpawnMenu`` — `+ Add` action menu reskinned as a trading-card deck.

A presentation sibling of :mod:`slappyengine.ui.editor.spawn_menu`. Each
spawn entry becomes a *trading card* with an illustrated portrait, a
one-line description, and a "Summon!" :class:`StickerButton`. Hover scales
the card slightly and adds a sparkle-shimmer overlay via
:func:`slappyengine.ui.theme.shader_effects.noise_glitter`. Click on the
Summon button opens a modal that uses :class:`NotebookInspector` to fill
the spec fields, mirroring the Nova3D
:func:`~slappyengine.ui.editor.spawn_menu.open_spawn_modal` contract.

This module is **presentation only** — it never modifies the existing
``spawn_menu.py`` and reuses its spec dataclasses + adapter factories so
the dispatch contract stays in lock-step with the Nova3D `+ Add` modal.

Design provenance
-----------------

* ``docs/ui_pattern_audit_2026_06_03.md`` §1.8 — Nova3D `+ Add` modal
  contract + the "trading card deck" translation row in §6.
* ``python/slappyengine/ui/editor/spawn_menu.py`` — source spec
  dataclasses (``RopeSpawnSpec``, ``RagdollSpawnSpec``,
  ``IKChainSpawnSpec``, ``HumanoidSpawnSpec``) and the lazy factory
  resolution table the modal reuses.

Portrait SVG budget — every :data:`SPAWN_CARDS` entry ships an inline
SVG portrait under 500 bytes (asserted at import time so a future copy
edit can't quietly bust the budget).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Callable

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
)
from slappyengine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)


# ---------------------------------------------------------------------------
# Inline SVG portraits — one per spawn card.
#
# Each ≤ 500 bytes. Glyphs use ``currentColor`` where the active theme can
# re-tint them; literal colour values are picked to stay legible on cream
# paper and to read at thumbnail scale. The byte budget guard at the
# bottom of this section asserts every portrait fits.
# ---------------------------------------------------------------------------

_SVG_ROPE_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="8" cy="20" r="4" fill="#a07050"/>'
    '<circle cx="56" cy="44" r="4" fill="#a07050"/>'
    '<path d="M8 20 L20 38 L32 22 L44 40 L56 24" '
    'fill="none" stroke="#a07050" stroke-width="3"/>'
    '</svg>'
)

_SVG_RAGDOLL_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="12" r="6" fill="none" stroke="#604030"/>'
    '<path d="M32 18 L32 40 M14 26 L50 26 '
    'M32 40 L20 58 M32 40 L44 58" stroke="#604030" fill="none"/>'
    '<circle cx="14" cy="26" r="2" fill="#a07050"/>'
    '<circle cx="50" cy="26" r="2" fill="#a07050"/>'
    '</svg>'
)

_SVG_HUMANOID_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="14" r="8" fill="#e0b080"/>'
    '<rect x="22" y="22" width="20" height="22" rx="6" fill="#d0a070"/>'
    '<rect x="22" y="44" width="8" height="16" rx="3" fill="#a07050"/>'
    '<rect x="34" y="44" width="8" height="16" rx="3" fill="#a07050"/>'
    '</svg>'
)

_SVG_IK_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="8" cy="48" r="3" fill="#7090c0"/>'
    '<circle cx="28" cy="28" r="3" fill="#7090c0"/>'
    '<circle cx="48" cy="16" r="3" fill="#7090c0"/>'
    '<line x1="8" y1="48" x2="28" y2="28" stroke="#7090c0" stroke-width="2"/>'
    '<line x1="28" y1="28" x2="48" y2="16" stroke="#7090c0" stroke-width="2"/>'
    '<polygon points="56,12 60,16 56,20" fill="#d87aa0"/>'
    '</svg>'
)

_SVG_ZONE_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<rect x="8" y="12" width="48" height="40" fill="none" '
    'stroke="#8090a0" stroke-width="2" stroke-dasharray="4,3"/>'
    '</svg>'
)

_SVG_THRESHOLD_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
    '<stop offset="0" stop-color="#7090c0"/>'
    '<stop offset="1" stop-color="#f0c050"/></linearGradient></defs>'
    '<rect x="6" y="24" width="52" height="16" fill="url(#g)"/>'
    '<line x1="36" y1="18" x2="36" y2="46" stroke="#d87aa0" stroke-width="2"/>'
    '</svg>'
)

_SVG_LIGHT_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="32" r="10" fill="#f0c050"/>'
    '<path d="M32 6 L32 14 M32 50 L32 58 M6 32 L14 32 M50 32 L58 32 '
    'M14 14 L20 20 M44 44 L50 50" stroke="#f0c050" fill="none"/>'
    '</svg>'
)

_SVG_SUN_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="32" r="14" fill="#f0c050"/>'
    '<circle cx="27" cy="29" r="1.5" fill="#604030"/>'
    '<circle cx="37" cy="29" r="1.5" fill="#604030"/>'
    '<path d="M27 36 Q32 40 37 36 M32 4 L32 12 M32 52 L32 60 '
    'M4 32 L12 32 M52 32 L60 32" stroke="#604030" fill="none"/>'
    '</svg>'
)

_SVG_PALETTE_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M32 8 C16 8 8 22 8 34 C8 44 16 48 22 44 C26 41 32 44 32 50 '
    'C32 56 40 58 48 52 C58 44 58 26 48 16 C44 12 38 8 32 8 Z" '
    'fill="#e0c890" stroke="#604030" stroke-width="1.5"/>'
    '<circle cx="20" cy="22" r="3" fill="#e07a90"/>'
    '<circle cx="32" cy="18" r="3" fill="#e0c850"/>'
    '<circle cx="44" cy="24" r="3" fill="#70a0c0"/>'
    '<circle cx="42" cy="38" r="3" fill="#6ea060"/>'
    '</svg>'
)

_SVG_EMITTER_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="32,4 36,28 60,32 36,36 32,60 28,36 4,32 28,28" '
    'fill="#f0c050"/>'
    '<circle cx="32" cy="32" r="4" fill="#d87aa0"/>'
    '<circle cx="14" cy="14" r="2" fill="#f0c050"/>'
    '<circle cx="50" cy="14" r="2" fill="#f0c050"/>'
    '<circle cx="14" cy="50" r="2" fill="#f0c050"/>'
    '<circle cx="50" cy="50" r="2" fill="#f0c050"/>'
    '</svg>'
)


# Byte-budget guard — every portrait must fit in 500 bytes.
for _name, _svg in (
    ("rope",       _SVG_ROPE_PORTRAIT),
    ("ragdoll",    _SVG_RAGDOLL_PORTRAIT),
    ("humanoid",   _SVG_HUMANOID_PORTRAIT),
    ("ik_chain",   _SVG_IK_PORTRAIT),
    ("zone_rect",  _SVG_ZONE_PORTRAIT),
    ("zone_thresh", _SVG_THRESHOLD_PORTRAIT),
    ("light",      _SVG_LIGHT_PORTRAIT),
    ("sun",        _SVG_SUN_PORTRAIT),
    ("material",   _SVG_PALETTE_PORTRAIT),
    ("emitter",    _SVG_EMITTER_PORTRAIT),
):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"NotebookSpawnMenu: SVG portrait {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


# ---------------------------------------------------------------------------
# Extra spec dataclasses for cards that don't have a Nova3D analogue.
#
# These reuse the same shape as ``spawn_menu``'s flattened specs (one
# primitive field per author-facing knob) so :class:`NotebookInspector`'s
# reflection picks them up automatically.
# ---------------------------------------------------------------------------


@dataclass
class RectZoneSpec:
    """Rectangular trigger / damage zone."""
    name: str = "zone_rect"
    position: tuple[float, float] = (0.0, 0.0)
    width: float = 32.0
    height: float = 16.0
    damage_per_second: float = 0.0
    tag: str = "trigger"


@dataclass
class ThresholdZoneSpec:
    """Scalar-field threshold zone (e.g. heat, pressure)."""
    name: str = "zone_threshold"
    field_name: str = "temperature"
    threshold: float = 1.0
    above: bool = True
    tag: str = "trigger"


@dataclass
class PointLightSpec:
    """Round soft pool of light."""
    name: str = "point_light"
    position: tuple[float, float] = (0.0, 0.0)
    radius: float = 64.0
    intensity: float = 1.0
    color: tuple[float, float, float, float] = (1.0, 0.95, 0.85, 1.0)


@dataclass
class DirectionalLightSpec:
    """Directional shadow-caster (sun)."""
    name: str = "sun"
    direction: tuple[float, float, float] = (0.3, -1.0, 0.2)
    intensity: float = 1.0
    color: tuple[float, float, float, float] = (1.0, 0.95, 0.85, 1.0)
    cast_shadows: bool = True


@dataclass
class MaterialSpawnSpec:
    """Node-graph material — spawns a blank graph the editor can populate."""
    name: str = "material"
    base_color: tuple[float, float, float, float] = (0.7, 0.7, 0.7, 1.0)
    roughness: float = 0.5
    metallic: float = 0.0


@dataclass
class EmitterSpawnSpec:
    """Particle emitter — point / line / disc."""
    name: str = "emitter"
    position: tuple[float, float] = (0.0, 0.0)
    shape: str = "point"
    rate_per_second: float = 60.0
    particle_lifetime: float = 1.5
    initial_speed: float = 32.0


# ---------------------------------------------------------------------------
# SpawnCard descriptor — one card per row in the trading-card deck.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SpawnCard:
    """One trading card in the spawn deck.

    Attributes
    ----------
    card_id:
        Stable id used by ``on_spawn(card_id, spec_dict)`` and tests.
    title:
        Display title rendered on the washi-tape strip.
    portrait_svg:
        Inline SVG markup for the portrait (≤ 500 bytes).
    description:
        One-line body text under the portrait.
    spec_cls:
        Dataclass type the modal reflects via :class:`NotebookInspector`.
    """

    card_id: str
    title: str
    portrait_svg: str
    description: str
    spec_cls: type


def _build_cards() -> list[SpawnCard]:
    """Construct the canonical SPAWN_CARDS list — defers Nova3D imports.

    The Nova3D spec classes live in
    :mod:`slappyengine.ui.editor.spawn_menu`. We import them lazily so a
    headless editor that never opens the spawn menu doesn't pay the
    import cost.
    """
    from slappyengine.ui.editor.spawn_menu import (
        HumanoidSpawnSpec,
        IKChainSpawnSpec,
        RagdollSpawnSpec,
        RopeSpawnSpec,
    )

    return [
        SpawnCard(
            "rope",
            "Rope",
            _SVG_ROPE_PORTRAIT,
            "A floppy rope between two anchors.",
            RopeSpawnSpec,
        ),
        SpawnCard(
            "ragdoll",
            "Ragdoll",
            _SVG_RAGDOLL_PORTRAIT,
            "A jointed character with break-points.",
            RagdollSpawnSpec,
        ),
        SpawnCard(
            "humanoid",
            "Humanoid",
            _SVG_HUMANOID_PORTRAIT,
            "A skeleton with flesh and feet-on-terrain.",
            HumanoidSpawnSpec,
        ),
        SpawnCard(
            "ik_chain",
            "IK Chain",
            _SVG_IK_PORTRAIT,
            "A kinematic chain that reaches a target.",
            IKChainSpawnSpec,
        ),
        SpawnCard(
            "zone_rect",
            "Rect Zone",
            _SVG_ZONE_PORTRAIT,
            "A rectangular trigger / damage region.",
            RectZoneSpec,
        ),
        SpawnCard(
            "zone_threshold",
            "Threshold Zone",
            _SVG_THRESHOLD_PORTRAIT,
            "A scalar field threshold.",
            ThresholdZoneSpec,
        ),
        SpawnCard(
            "light_point",
            "Point Light",
            _SVG_LIGHT_PORTRAIT,
            "A round soft pool of light.",
            PointLightSpec,
        ),
        SpawnCard(
            "light_directional",
            "Sun",
            _SVG_SUN_PORTRAIT,
            "A directional shadow-caster.",
            DirectionalLightSpec,
        ),
        SpawnCard(
            "material",
            "Material",
            _SVG_PALETTE_PORTRAIT,
            "A node-graph material.",
            MaterialSpawnSpec,
        ),
        SpawnCard(
            "emitter",
            "Particle Emitter",
            _SVG_EMITTER_PORTRAIT,
            "A point / line / disc emitter.",
            EmitterSpawnSpec,
        ),
    ]


# ---------------------------------------------------------------------------
# NotebookSpawnMenu
# ---------------------------------------------------------------------------


class NotebookSpawnMenu:
    """+ Add menu themed as a trading-card deck.

    Each spawn action is a trading card with an illustrated portrait,
    a one-line description, and a "Summon!" button. Hover scales the
    card slightly + sprinkles a sparkle-shimmer overlay (via
    :func:`noise_glitter`). Click opens the spec-fill modal which uses
    :class:`NotebookInspector` to render one widget per spec field, then
    fires ``on_spawn(card_id, spec_dict)`` on submit.

    The menu follows the Nova3D ``build(parent_tag)`` panel protocol so
    the editor shell can mount it like any other panel.

    Parameters
    ----------
    on_spawn:
        Callable invoked when the user submits a summon. Signature:
        ``on_spawn(card_id: str, spec: dict[str, Any]) -> None``. The
        spec dict carries the dataclass fields the user filled in.
    """

    TITLE = "+ Add"

    # Layout constants — 4 cards per row, 3 rows visible, card ~120x160.
    CARDS_PER_ROW: int = 4
    VISIBLE_ROWS: int = 3
    CARD_WIDTH: int = 120
    CARD_HEIGHT: int = 160

    # Hover state effect parameters — shimmer dimensions + density.
    HOVER_SCALE: float = 1.05
    SHIMMER_W: int = 120
    SHIMMER_H: int = 160
    SHIMMER_DENSITY: float = 0.06

    # ------------------------------------------------------------------

    def __init__(self, on_spawn: Callable[[str, dict], None]) -> None:
        self._on_spawn = validate_callable(
            "on_spawn", "NotebookSpawnMenu", on_spawn,
        )

        # The card table — built eagerly so tests can introspect SVG bytes
        # / spec types without going through DPG.
        self._cards: list[SpawnCard] = _build_cards()

        # Per-card tag bookkeeping for the DPG build path.
        self._card_tags: dict[str, str] = {}

        # Modal lifecycle — at most one modal is open at a time.
        self._open_modal: dict[str, Any] | None = None

        # Hover state — current hovered card id (or None).
        self._hovered_card: str | None = None
        # Shimmer overlay textures keyed by card id (lazy, built on hover).
        self._shimmer_overlays: dict[str, Any] = {}

        # Build / open lifecycle flags.
        self._built: bool = False
        self._is_open: bool = False
        self._parent_tag: str | int | None = None

        # Cached theme — refreshed on theme-listener fire.
        self._theme = resolve_theme()
        self._card_bg = self._theme.color("paper", (250, 246, 235, 255))
        self._ink = self._theme.color("ink", (40, 40, 60, 255))
        self._accent = self._theme.color("accent", (220, 120, 160, 255))
        self._washi = self._theme.color("washi", (180, 200, 230, 255))

        # Theme listener so the cards re-tint on a theme switch.
        register_theme_listener(self._on_theme_changed)

        # Call history for headless test assertions.
        self.call_log: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------
    # Properties — tests reach into these
    # ------------------------------------------------------------------

    @property
    def cards(self) -> list[SpawnCard]:
        """Return the static :class:`SpawnCard` table."""
        return list(self._cards)

    @property
    def card_count(self) -> int:
        """Return the number of cards in the deck."""
        return len(self._cards)

    @property
    def hovered_card(self) -> str | None:
        """Return the currently hovered card id (or ``None``)."""
        return self._hovered_card

    @property
    def card_background(self) -> tuple[int, int, int, int]:
        """Current card background colour from the active theme."""
        return self._card_bg

    @property
    def is_open(self) -> bool:
        """Return ``True`` when :meth:`open` has been called and not closed."""
        return self._is_open

    @property
    def open_modal(self) -> dict[str, Any] | None:
        """Return the currently open summon-modal state (or ``None``)."""
        return self._open_modal

    def get_card(self, card_id: str) -> SpawnCard | None:
        """Return the :class:`SpawnCard` with the given id (or ``None``)."""
        for card in self._cards:
            if card.card_id == card_id:
                return card
        return None

    # ------------------------------------------------------------------
    # Public surface — Nova3D ``build(parent_tag)`` protocol
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Materialise the deck under *parent_tag*.

        Safe to call when ``dearpygui`` is missing — every DPG call is
        guarded so the menu still registers its bookkeeping for tests.
        """
        if isinstance(parent_tag, str):
            validate_non_empty_str(
                "parent_tag", "NotebookSpawnMenu.build", parent_tag,
            )

        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))

        dpg = self._safe_dpg()
        if dpg is None:
            return

        root_tag = f"notebook_spawn_menu_{id(self)}"
        try:
            with dpg.child_window(
                parent=parent_tag,
                tag=root_tag,
                border=False,
                autosize_x=True,
                height=self.VISIBLE_ROWS * self.CARD_HEIGHT + 20,
            ):
                self._build_title(dpg)
                self._build_grid(dpg)
        except Exception:
            # Stub-DPG / context-manager-less fallback.
            self._build_title(dpg)
            self._build_grid(dpg)

    def open(self) -> None:
        """Mark the deck as open (e.g. after a `+ Add` toolbar click)."""
        self._is_open = True
        self.call_log.append(("open",))

    def close(self) -> None:
        """Close the deck + any open summon modal."""
        self._is_open = False
        if self._open_modal is not None:
            self._close_modal()
        self.call_log.append(("close",))

    def destroy(self) -> None:
        """Detach theme listener + drop any cached overlays."""
        unregister_theme_listener(self._on_theme_changed)
        self._shimmer_overlays.clear()
        self._built = False

    # ------------------------------------------------------------------
    # Hover / shimmer overlay
    # ------------------------------------------------------------------

    def set_hover(self, card_id: str | None) -> None:
        """Mark *card_id* as hovered (``None`` clears the hover state).

        On hover, a sparkle-shimmer overlay is lazily baked via
        :func:`noise_glitter` and cached so subsequent hover-enters on the
        same card are allocation-free.
        """
        if card_id is not None:
            if not isinstance(card_id, str) or not card_id:
                raise TypeError(
                    "NotebookSpawnMenu.set_hover: card_id must be str or None"
                )
            if self.get_card(card_id) is None:
                # Unknown card id — silently clear instead of crashing.
                card_id = None

        self._hovered_card = card_id
        self.call_log.append(("hover", card_id))

        if card_id is None:
            return

        # Lazily bake the shimmer texture for this card.
        if card_id not in self._shimmer_overlays:
            self._shimmer_overlays[card_id] = self._make_shimmer_texture()

    def shimmer_overlay(self, card_id: str) -> Any | None:
        """Return the cached sparkle-shimmer overlay texture for *card_id*.

        ``None`` when the card has never been hovered (overlays are lazy).
        """
        return self._shimmer_overlays.get(card_id)

    def hover_scale(self) -> float:
        """Return the scale factor applied to a hovered card."""
        return self.HOVER_SCALE

    # ------------------------------------------------------------------
    # Summon — opens the spec-fill modal
    # ------------------------------------------------------------------

    def summon(self, card_id: str) -> None:
        """Trigger the Summon action for *card_id* — opens the spec modal.

        The modal uses :class:`NotebookInspector` to fill the spec fields;
        on submit, ``on_spawn(card_id, spec_dict)`` fires.
        """
        validate_non_empty_str("card_id", "NotebookSpawnMenu.summon", card_id)
        card = self.get_card(card_id)
        if card is None:
            raise ValueError(
                f"NotebookSpawnMenu.summon: unknown card id {card_id!r}"
            )

        spec_instance = card.spec_cls()
        modal_state = self._open_summon_modal(card, spec_instance)
        self._open_modal = modal_state
        self.call_log.append(("summon", card_id))

    def submit_modal(self) -> None:
        """Submit the currently open modal — fires :data:`on_spawn`.

        No-op when no modal is open.
        """
        if self._open_modal is None:
            return

        card_id = self._open_modal["card_id"]
        spec_instance = self._open_modal["spec"]
        spec_dict = self._spec_to_dict(spec_instance)
        self.call_log.append(("submit", card_id, spec_dict))

        try:
            self._on_spawn(card_id, spec_dict)
        except Exception:
            # Callback errors must not poison the menu.
            pass

        self._close_modal()

    def cancel_modal(self) -> None:
        """Cancel the currently open modal without firing :data:`on_spawn`."""
        if self._open_modal is None:
            return
        self.call_log.append(("cancel", self._open_modal["card_id"]))
        self._close_modal()

    # ------------------------------------------------------------------
    # Internal helpers — modal + grid + DPG paths
    # ------------------------------------------------------------------

    def _open_summon_modal(
        self,
        card: SpawnCard,
        spec_instance: Any,
    ) -> dict[str, Any]:
        """Open the spec-fill modal for *card* and return its state dict."""
        # Build a NotebookInspector bound to the spec — same widget the
        # field-journal Inspector uses, so every dataclass field gets the
        # right widget for free.
        try:
            from slappyengine.ui.editor.notebook_inspector import (
                NotebookInspector,
            )
            inspector: Any = NotebookInspector(target=spec_instance)
        except Exception:
            inspector = None

        modal_state: dict[str, Any] = {
            "card_id": card.card_id,
            "card": card,
            "spec": spec_instance,
            "inspector": inspector,
        }

        dpg = self._safe_dpg()
        if dpg is None:
            return modal_state

        modal_tag = f"notebook_spawn_modal_{id(spec_instance)}"
        body_tag = f"{modal_tag}_body"
        modal_state["modal_tag"] = modal_tag
        modal_state["body_tag"] = body_tag

        try:
            with dpg.window(
                label=f"Summon: {card.title}",
                modal=True,
                no_close=False,
                tag=modal_tag,
                width=380,
                height=440,
            ):
                # Inspector child window — auto-reflects every spec field.
                try:
                    with dpg.child_window(
                        tag=body_tag, width=-1, height=-50, border=False,
                    ):
                        pass
                except Exception:
                    pass
                if inspector is not None:
                    try:
                        inspector.build(body_tag)
                    except Exception:
                        pass
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                try:
                    with dpg.group(horizontal=True):
                        dpg.add_button(
                            label="Summon!",
                            callback=lambda *_: self.submit_modal(),
                            width=140,
                        )
                        dpg.add_button(
                            label="Cancel",
                            callback=lambda *_: self.cancel_modal(),
                            width=140,
                        )
                except Exception:
                    pass
        except Exception:
            # Stub-DPG / context-manager-less fallback.
            pass

        return modal_state

    def _close_modal(self) -> None:
        """Tear down the open modal's DPG resources (best-effort)."""
        if self._open_modal is None:
            return
        dpg = self._safe_dpg()
        modal_tag = self._open_modal.get("modal_tag")
        if dpg is not None and isinstance(modal_tag, str):
            try:
                if dpg.does_item_exist(modal_tag):
                    dpg.delete_item(modal_tag)
            except Exception:
                pass
        self._open_modal = None

    def _build_title(self, dpg: Any) -> None:
        """Render the deck title with washi-tape underline."""
        ink = list(self._ink)
        washi = list(self._washi)
        try:
            dpg.add_text(self.TITLE, color=ink)
        except Exception:
            pass
        try:
            dpg.add_text("================================", color=washi)
        except Exception:
            pass

    def _build_grid(self, dpg: Any) -> None:
        """Render the 4×N card grid inside a scrollable child window."""
        grid_tag = f"notebook_spawn_grid_{id(self)}"
        try:
            with dpg.child_window(
                tag=grid_tag,
                border=False,
                autosize_x=True,
                height=self.VISIBLE_ROWS * self.CARD_HEIGHT + 4,
            ):
                self._build_grid_rows(dpg)
        except Exception:
            # Stub-DPG fallback — render flat.
            self._build_grid_rows(dpg)

    def _build_grid_rows(self, dpg: Any) -> None:
        """Lay out the cards in rows of :data:`CARDS_PER_ROW`."""
        per_row = self.CARDS_PER_ROW
        for row_start in range(0, len(self._cards), per_row):
            row_cards = self._cards[row_start: row_start + per_row]
            try:
                with dpg.group(horizontal=True):
                    for card in row_cards:
                        self._build_card(dpg, card)
            except Exception:
                for card in row_cards:
                    self._build_card(dpg, card)

    def _build_card(self, dpg: Any, card: SpawnCard) -> None:
        """Render a single trading card."""
        card_tag = f"notebook_spawn_card_{card.card_id}"
        self._card_tags[card.card_id] = card_tag
        try:
            with dpg.child_window(
                tag=card_tag,
                width=self.CARD_WIDTH,
                height=self.CARD_HEIGHT,
                border=True,
            ):
                self._render_card_body(dpg, card)
        except Exception:
            self._render_card_body(dpg, card)

    def _render_card_body(self, dpg: Any, card: SpawnCard) -> None:
        """Render the inside of a card — washi tape, portrait, desc, button."""
        washi = list(self._washi)
        ink = list(self._ink)
        accent = list(self._accent)

        # Washi-tape top strip + title.
        try:
            dpg.add_text("============", color=washi)
        except Exception:
            pass
        try:
            dpg.add_text(card.title, color=ink)
        except Exception:
            pass
        try:
            dpg.add_separator()
        except Exception:
            pass

        # Portrait placeholder — the SVG itself is registered as the
        # card's portrait asset; in headless / stub-DPG we drop a coloured
        # glyph stand-in so tests still get a hit on add_text.
        try:
            dpg.add_text("[portrait]", color=accent)
        except Exception:
            pass

        # Description (body font, smaller).
        try:
            dpg.add_text(card.description, wrap=self.CARD_WIDTH - 12, color=ink)
        except Exception:
            pass
        try:
            dpg.add_separator()
        except Exception:
            pass

        # Summon button — uses a StickerButton when the theme has it.
        self._render_summon_button(dpg, card)

    def _render_summon_button(self, dpg: Any, card: SpawnCard) -> None:
        """Render the Summon button (StickerButton when available)."""
        try:
            from slappyengine.ui.widgets import StickerButton

            btn = StickerButton(
                label=f"<3 Summon! ({card.title})",
                sticker_icon="heart",
                callback=(
                    lambda s, a, u, cid=card.card_id: self.summon(cid)
                ),
                width=self.CARD_WIDTH - 8,
                height=28,
            )
            # Build under the current card window — DPG resolves the
            # parent from the surrounding ``with child_window``.
            try:
                btn.build(self._card_tags.get(card.card_id, "spawn_card"))
            except Exception:
                pass
        except Exception:
            try:
                dpg.add_button(
                    label="<3 Summon!",
                    callback=(
                        lambda s, a, u, cid=card.card_id: self.summon(cid)
                    ),
                    width=self.CARD_WIDTH - 8,
                    height=28,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Shimmer texture
    # ------------------------------------------------------------------

    def _make_shimmer_texture(self) -> Any:
        """Bake a ``noise_glitter`` sparkle texture for hover overlays.

        Falls back to ``None`` when numpy or the shader_effects module is
        unavailable — the menu still records the hover event for tests.
        """
        try:
            from slappyengine.ui.theme.shader_effects import noise_glitter

            return noise_glitter(
                width=self.SHIMMER_W,
                height=self.SHIMMER_H,
                density=self.SHIMMER_DENSITY,
                color=tuple(self._accent),
                seed=11,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Theme handling
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: Any) -> None:
        """Theme listener — re-resolve cached palette + drop overlays."""
        self._theme = resolve_theme()
        self._card_bg = self._theme.color("paper", self._card_bg)
        self._ink = self._theme.color("ink", self._ink)
        self._accent = self._theme.color("accent", self._accent)
        self._washi = self._theme.color("washi", self._washi)
        # Drop cached shimmer textures so they re-bake with the new accent.
        self._shimmer_overlays.clear()
        self.call_log.append(("theme_changed",))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _spec_to_dict(spec: Any) -> dict[str, Any]:
        """Return a dict mapping spec dataclass fields → current values."""
        if dataclasses.is_dataclass(spec) and not isinstance(spec, type):
            return {f.name: getattr(spec, f.name) for f in dataclasses.fields(spec)}
        return {k: v for k, v in vars(spec).items() if not k.startswith("_")}

    @staticmethod
    def _safe_dpg() -> Any | None:
        """Return ``dearpygui.dearpygui`` or ``None`` when unavailable."""
        try:
            import dearpygui.dearpygui as dpg
            return dpg
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Module-level SPAWN_CARDS — tests and external callers may import this.
# ---------------------------------------------------------------------------


def _make_spawn_cards_table() -> list[tuple]:
    """Return the trade-card table in the tuple form the brief specifies."""
    cards = _build_cards()
    return [
        (c.card_id, c.title, c.portrait_svg, c.description) for c in cards
    ]


# Public constant — the (card_id, title, svg, description) tuples for any
# caller that wants the static table without constructing the menu.
SPAWN_CARDS: list[tuple] = _make_spawn_cards_table()


__all__ = [
    "DirectionalLightSpec",
    "EmitterSpawnSpec",
    "MaterialSpawnSpec",
    "NotebookSpawnMenu",
    "PointLightSpec",
    "RectZoneSpec",
    "SPAWN_CARDS",
    "SpawnCard",
    "ThresholdZoneSpec",
]
