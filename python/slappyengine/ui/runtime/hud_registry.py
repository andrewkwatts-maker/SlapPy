"""Factory registry for HUD widgets.

Games (and the editor) can look up HUD widgets by name and instantiate
them from a config dict — handy for data-driven HUD layouts stored in
YAML/JSON alongside the scene. The registry ships with the nine
first-party widgets pre-registered:

* ``health_bar``, ``stamina_bar``, ``ammo_counter`` — from :mod:`hud_kit`.
* ``compass``, ``minimap``, ``toast`` — also from :mod:`hud_kit`.
* ``crosshair``, ``score_counter``, ``objective_marker`` — from
  :mod:`hud_kit_extra`.

Third-party widgets can be added at runtime via :meth:`register`; the
registry never persists across processes, so the pre-registered set is
rebuilt from :func:`_default_factories` at construction time.
"""
from __future__ import annotations

from typing import Any, Callable

from .hud_kit import (
    AmmoCounter,
    Compass,
    HealthBar,
    Minimap,
    StaminaBar,
    Toast,
)
from .hud_kit_extra import Crosshair, ObjectiveMarker, ScoreCounter


WidgetFactory = Callable[[dict[str, Any]], Any]


def _apply_config(widget: Any, config: dict[str, Any]) -> Any:
    """Assign every ``config`` key onto ``widget`` if the attribute exists.

    Missing / typo'd keys are ignored so a shared config schema can
    address multiple widget types without runtime errors.
    """
    if not config:
        return widget
    for key, value in config.items():
        if hasattr(widget, key):
            try:
                setattr(widget, key, value)
            except Exception:
                continue
    return widget


def _default_factories() -> dict[str, WidgetFactory]:
    """Build the pre-registered widget → factory table."""

    def make_health_bar(cfg: dict[str, Any]) -> HealthBar:
        return _apply_config(HealthBar(), cfg or {})

    def make_stamina_bar(cfg: dict[str, Any]) -> StaminaBar:
        return _apply_config(StaminaBar(), cfg or {})

    def make_ammo_counter(cfg: dict[str, Any]) -> AmmoCounter:
        return _apply_config(AmmoCounter(), cfg or {})

    def make_compass(cfg: dict[str, Any]) -> Compass:
        return _apply_config(Compass(), cfg or {})

    def make_minimap(cfg: dict[str, Any]) -> Minimap:
        return _apply_config(Minimap(), cfg or {})

    def make_toast(cfg: dict[str, Any]) -> Toast:
        return _apply_config(Toast(), cfg or {})

    def make_crosshair(cfg: dict[str, Any]) -> Crosshair:
        return _apply_config(Crosshair(), cfg or {})

    def make_score_counter(cfg: dict[str, Any]) -> ScoreCounter:
        return _apply_config(ScoreCounter(), cfg or {})

    def make_objective_marker(cfg: dict[str, Any]) -> ObjectiveMarker:
        return _apply_config(ObjectiveMarker(), cfg or {})

    return {
        "health_bar": make_health_bar,
        "stamina_bar": make_stamina_bar,
        "ammo_counter": make_ammo_counter,
        "compass": make_compass,
        "minimap": make_minimap,
        "toast": make_toast,
        "crosshair": make_crosshair,
        "score_counter": make_score_counter,
        "objective_marker": make_objective_marker,
    }


class HUDRegistry:
    """Named-factory registry for HUD widgets.

    Usage::

        registry = HUDRegistry()
        bar = registry.create("health_bar", {"value": 60, "max_value": 100})
        overlay.attach(bar)
    """

    def __init__(self) -> None:
        self._factories: dict[str, WidgetFactory] = _default_factories()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, name: str, factory: WidgetFactory) -> None:
        """Register a new widget under *name*.

        Raises
        ------
        ValueError
            If *name* is empty.
        TypeError
            If *factory* is not callable.
        """
        if not isinstance(name, str) or not name:
            raise ValueError(
                "HUDRegistry.register: name must be a non-empty str; "
                f"got {name!r}"
            )
        if not callable(factory):
            raise TypeError(
                "HUDRegistry.register: factory must be callable; "
                f"got {type(factory).__name__}"
            )
        self._factories[name] = factory

    def unregister(self, name: str) -> bool:
        """Remove *name* from the registry; returns True when it was found."""
        return self._factories.pop(name, None) is not None

    # ------------------------------------------------------------------
    # Instantiation
    # ------------------------------------------------------------------

    def create(self, name: str, config: dict[str, Any] | None = None) -> Any:
        """Instantiate the widget registered under *name*.

        Raises
        ------
        KeyError
            If *name* is not registered.
        """
        factory = self._factories.get(name)
        if factory is None:
            raise KeyError(
                f"HUDRegistry.create: no widget registered under {name!r}"
            )
        return factory(config or {})

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def list_available(self) -> list[str]:
        """Return the sorted list of registered widget names."""
        return sorted(self._factories.keys())

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._factories

    def __len__(self) -> int:
        return len(self._factories)


__all__ = ["HUDRegistry", "WidgetFactory"]
