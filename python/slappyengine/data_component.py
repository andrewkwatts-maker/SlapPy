from __future__ import annotations
from typing import Any, Callable


class DataComponent:
    """
    Generic key-value data store with reactive field watchers.

    Attach to any entity or asset to give it named state.
    Watchers fire synchronously when a field changes.

    Usage:
        entity.data = DataComponent(hp=100, speed=5.0, state="idle")

        # React to field changes:
        entity.data.watch("hp", lambda old, new: print(f"HP {old}→{new}"))
        entity.data.watch("state", lambda old, new: entity.on_state_change(old, new))

        # Read/write:
        entity.data.hp -= 10      # fires watchers
        val = entity.data.speed   # 5.0

        # Batch update (fires watchers once per field):
        entity.data.set(hp=90, state="hurt")

        # Condition binding (checked on .tick()):
        entity.data.bind(
            when=lambda d: d.get("hp", 1) <= 0,
            then=lambda d: entity.bus.publish("destroyed", entity=entity),
        )
    """

    __slots__ = ("_fields", "_watchers", "_bindings")

    def __init__(self, **fields: Any) -> None:
        object.__setattr__(self, "_fields", dict(fields))
        object.__setattr__(self, "_watchers", {})   # field → [callable(old, new)]
        object.__setattr__(self, "_bindings", [])   # [(predicate, action, once)]

    # ── Attribute protocol ────────────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        fields = object.__getattribute__(self, "_fields")
        try:
            return fields[name]
        except KeyError:
            raise AttributeError(f"DataComponent has no field {name!r}") from None

    def __setattr__(self, name: str, value: Any) -> None:
        fields = object.__getattribute__(self, "_fields")
        old = fields.get(name)
        fields[name] = value
        watchers = object.__getattribute__(self, "_watchers")
        for cb in list(watchers.get(name, [])):
            try:
                cb(old, value)
            except Exception:
                pass

    def __contains__(self, name: str) -> bool:
        return name in object.__getattribute__(self, "_fields")

    # ── Helpers ───────────────────────────────────────────────────────────

    def get(self, name: str, default: Any = None) -> Any:
        return object.__getattribute__(self, "_fields").get(name, default)

    def set(self, **kwargs: Any) -> None:
        """Batch-set multiple fields (each fires its own watchers)."""
        for k, v in kwargs.items():
            setattr(self, k, v)

    def to_dict(self) -> dict[str, Any]:
        return dict(object.__getattribute__(self, "_fields"))

    # ── Watchers ─────────────────────────────────────────────────────────

    def watch(self, field: str, callback: Callable[[Any, Any], None]) -> None:
        """Register callback(old_value, new_value) fired on field change."""
        watchers = object.__getattribute__(self, "_watchers")
        watchers.setdefault(field, []).append(callback)

    def unwatch(self, field: str, callback: Callable) -> None:
        watchers = object.__getattribute__(self, "_watchers")
        lst = watchers.get(field, [])
        try:
            lst.remove(callback)
        except ValueError:
            pass

    # ── Condition bindings ────────────────────────────────────────────────

    def bind(
        self,
        when: Callable[["DataComponent"], bool],
        then: Callable[["DataComponent"], None],
        once: bool = True,
    ) -> None:
        """
        Register a condition→action pair evaluated on .tick().

        when(data)  → bool : predicate
        then(data)  → None : action fired when predicate is True
        once        → bool : remove after first firing (default True)
        """
        bindings = object.__getattribute__(self, "_bindings")
        bindings.append({"when": when, "then": then, "once": once, "fired": False})

    def tick(self) -> None:
        """Evaluate all condition bindings. Call once per simulation tick."""
        bindings = object.__getattribute__(self, "_bindings")
        to_remove = []
        for b in bindings:
            if b.get("fired") and b.get("once"):
                to_remove.append(b)
                continue
            try:
                if b["when"](self):
                    b["then"](self)
                    b["fired"] = True
                    if b["once"]:
                        to_remove.append(b)
            except Exception:
                pass
        for b in to_remove:
            try:
                bindings.remove(b)
            except ValueError:
                pass

    def __repr__(self) -> str:
        return f"DataComponent({object.__getattribute__(self, '_fields')!r})"
