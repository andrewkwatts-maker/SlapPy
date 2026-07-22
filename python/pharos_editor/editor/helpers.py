"""Editor helper one-liners exposed through the REPL panel.

The user's directive (CCC2 sprint):

    "having exposed functions / helper functions" — so a developer sitting
    in the editor can drop into the REPL and script the scene with a
    single call per action.

Every helper here is a thin façade over :class:`pharos_engine.App` (for
spawning / mutating handles) or over :class:`pharos_engine.scene.Scene`
(for whole-scene save/load). The functions accept an optional ``app=``
kwarg (defaulting to the implicit global :class:`App`) so the REPL panel
can inject a specific app instance while ad-hoc callers just call
``spawn_cube()`` and let the module find the running app.

Public contract
---------------

The module exports 21 helpers:

* Spawning:   ``spawn_cube``, ``spawn_sphere``, ``spawn_plane``,
              ``spawn_light``, ``set_camera``
* Loading:    ``load_model``, ``load_texture``, ``load_shader``
* Selection:  ``list_entities``, ``select``
* Transforms: ``move``, ``rotate``, ``scale``
* Lifecycle:  ``delete``, ``clear_scene``
* Scene IO:   ``save_scene``, ``load_scene``, ``set_background``
* Capture:    ``screenshot``, ``record_gif``
* Discovery:  ``help`` (returns a markdown cheat sheet)

Every function carries a docstring — the ``help()`` helper introspects
this module to render the full cheat sheet at runtime, so adding a new
helper automatically extends the REPL's ``/help`` output.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — import guarded to keep module cheap
    from pharos_engine.app import (
        App,
        CameraHandle,
        LightHandle,
        ModelHandle,
        TextureHandle,
    )


# ---------------------------------------------------------------------------
# Handle types for `load_shader` — kept ultra-light so importing this
# module never pulls the whole shader stack. Real shader compilation is
# left to :mod:`pharos_engine.shader_gen`; the helper returns a bare
# metadata dict wrapped in :class:`ShaderHandle` for a REPL-friendly repr.
# ---------------------------------------------------------------------------


class ShaderHandle:
    """Lightweight handle to a WGSL shader loaded from disk.

    Attributes
    ----------
    path
        Absolute path of the source file (as passed to :func:`load_shader`).
    source
        The raw WGSL text — cached so the caller can inspect it in the REPL
        without a second disk read.
    """

    __slots__ = ("path", "source")

    def __init__(self, path: str, source: str) -> None:
        self.path = path
        self.source = source

    def __repr__(self) -> str:  # pragma: no cover — repr helper
        return f"ShaderHandle(path={self.path!r}, lines={self.source.count(chr(10)) + 1})"


# ---------------------------------------------------------------------------
# Implicit app resolution
# ---------------------------------------------------------------------------


def _resolve_app(app: "App | None" = None) -> "App":
    """Return *app* when given, else the implicit global :class:`App`.

    Centralised so every helper handles the ``app=`` kwarg the same way —
    the REPL panel passes an explicit app; ad-hoc callers get the
    implicit-global path baked into :class:`App`.
    """
    if app is not None:
        return app
    from pharos_engine.app import App as _App

    return _App._get_implicit()


# ---------------------------------------------------------------------------
# Spawning helpers
# ---------------------------------------------------------------------------


def spawn_cube(
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    size: float = 1.0,
    color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    *,
    app: "App | None" = None,
) -> "ModelHandle":
    """Spawn a unit cube primitive and return its :class:`ModelHandle`.

    A primitive is a bare ``ModelHandle`` with ``path`` set to
    ``"primitive:cube"`` — the renderer soft-imports the built-in mesh
    when it sees this sentinel. Trace-logged so headless tests can
    assert on the spawn.
    """
    a = _resolve_app(app)
    handle = a.load_model("primitive:cube")
    handle.position = tuple(float(x) for x in position)
    handle.scale = (float(size), float(size), float(size))
    a.trace.append(("spawn_cube", handle.id, tuple(color)))
    return handle


def spawn_sphere(
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    radius: float = 0.5,
    color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    *,
    app: "App | None" = None,
) -> "ModelHandle":
    """Spawn a unit sphere primitive and return its :class:`ModelHandle`.

    Uses the ``"primitive:sphere"`` sentinel. Scale is set uniformly to
    ``radius`` so the resulting handle drives the renderer at the caller's
    requested size.
    """
    a = _resolve_app(app)
    handle = a.load_model("primitive:sphere")
    handle.position = tuple(float(x) for x in position)
    handle.scale = (float(radius), float(radius), float(radius))
    a.trace.append(("spawn_sphere", handle.id, tuple(color)))
    return handle


def spawn_plane(
    position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    size: tuple[float, float] = (10.0, 10.0),
    color: tuple[float, float, float] = (0.5, 0.5, 0.5),
    *,
    app: "App | None" = None,
) -> "ModelHandle":
    """Spawn a horizontal plane primitive and return its :class:`ModelHandle`.

    Uses the ``"primitive:plane"`` sentinel. The plane lies in the XZ plane
    with the caller-supplied ``size`` mapped onto X + Z scale (Y stays at 1).
    """
    a = _resolve_app(app)
    handle = a.load_model("primitive:plane")
    handle.position = tuple(float(x) for x in position)
    handle.scale = (float(size[0]), 1.0, float(size[1]))
    a.trace.append(("spawn_plane", handle.id, tuple(color)))
    return handle


def spawn_light(
    position: tuple[float, float, float] = (5.0, 5.0, 5.0),
    color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    intensity: float = 1.0,
    *,
    app: "App | None" = None,
) -> "LightHandle":
    """Spawn a point light — thin wrapper over :meth:`App.spawn_light`."""
    return _resolve_app(app).spawn_light(
        position=position, color=color, intensity=intensity,
    )


def set_camera(
    position: tuple[float, float, float] = (0.0, 0.0, 5.0),
    look_at: tuple[float, float, float] = (0.0, 0.0, 0.0),
    *,
    app: "App | None" = None,
) -> "CameraHandle":
    """Spawn / activate a camera at *position* aimed at *look_at*.

    Delegates to :meth:`App.spawn_camera` (which marks the returned handle
    as :attr:`App.active_camera`).
    """
    return _resolve_app(app).spawn_camera(position=position, look_at=look_at)


# ---------------------------------------------------------------------------
# Asset loading
# ---------------------------------------------------------------------------


def load_model(path: str | Path, *, app: "App | None" = None) -> "ModelHandle":
    """Load a model asset — delegates to :func:`pharos_engine.load_model`."""
    return _resolve_app(app).load_model(path)


def load_texture(
    path: str | Path, *, app: "App | None" = None
) -> "TextureHandle":
    """Load a texture asset — delegates to :meth:`App.load_texture`."""
    return _resolve_app(app).load_texture(path)


def load_shader(path: str | Path, *, app: "App | None" = None) -> ShaderHandle:
    """Load a WGSL shader from disk and return a :class:`ShaderHandle`.

    Reads the file as UTF-8 text (WGSL is always text) and returns a
    lightweight handle so the caller can inspect ``.source`` at the REPL
    or hand it off to :mod:`pharos_engine.shader_gen`.

    Trace-logged on the resolved :class:`App` so headless tests can
    assert on the load.
    """
    p = Path(path)
    source = p.read_text(encoding="utf-8")
    handle = ShaderHandle(str(p), source)
    _resolve_app(app).trace.append(("load_shader", str(p), len(source)))
    return handle


def reload_shader(path: str | Path, *, app: "App | None" = None) -> Any:
    """Hot-reload the WGSL shader at *path* through the default reloader.

    Reads *path* off disk, hands the fresh source to the process-wide
    :class:`ShaderHotReloader` (which validates + emits
    ``shader.reloaded`` on the event bus), and returns the
    :class:`CompileResult`. When the shader hasn't been registered yet
    the reloader auto-registers a no-op callback so REPL callers don't
    need to plumb one through.

    Trace-logged on the resolved :class:`App` so headless tests can
    assert on the reload.
    """
    from pharos_engine.render.shader_hot_reload import get_default_reloader

    p = Path(path)
    source = p.read_text(encoding="utf-8")
    reloader = get_default_reloader()
    if str(p.resolve()) not in reloader.registered_paths():
        reloader.register(str(p), lambda _src: None)
    result = reloader.recompile(str(p), source)
    _resolve_app(app).trace.append(
        ("reload_shader", str(p), bool(result.ok)),
    )
    return result


# ---------------------------------------------------------------------------
# Selection + introspection
# ---------------------------------------------------------------------------


def list_entities(*, app: "App | None" = None) -> list[Any]:
    """Return all live entities — models, lights, cameras — as a flat list.

    Used by the REPL panel's default ``entities`` binding so the user can
    ``for e in list_entities(): ...`` without knowing about the individual
    :attr:`App.models` / :attr:`App.lights` / :attr:`App.cameras` lists.
    """
    a = _resolve_app(app)
    return list(a.models) + list(a.lights) + list(a.cameras)


def select(entity_id: int, *, app: "App | None" = None) -> Any:
    """Return the entity with :attr:`~ModelHandle.id` == *entity_id* or ``None``.

    Searches models → lights → cameras in that order (matching the trace's
    monotonic id allocator). Returns ``None`` when no entity matches so
    REPL code can guard with a simple truthiness check.
    """
    a = _resolve_app(app)
    for coll in (a.models, a.lights, a.cameras):
        for e in coll:
            if getattr(e, "id", -1) == int(entity_id):
                return e
    return None


# ---------------------------------------------------------------------------
# Transform helpers — accept any handle that carries a mutable
# ``.position`` / ``.rotation`` / ``.scale`` tuple. Duck-typed so future
# entity subclasses drop straight in without a helper rewrite.
# ---------------------------------------------------------------------------


def move(
    entity: Any, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0,
) -> Any:
    """Translate *entity* by (dx, dy, dz). Returns *entity* for chaining.

    Prefers :meth:`ModelHandle.move_by` when available so trace-logs stay
    consistent; falls back to a raw tuple assignment for lights + cameras.
    """
    move_by = getattr(entity, "move_by", None)
    if callable(move_by):
        return move_by(dx, dy, dz)
    x, y, z = getattr(entity, "position", (0.0, 0.0, 0.0))
    entity.position = (float(x + dx), float(y + dy), float(z + dz))
    return entity


def rotate(
    entity: Any, rx: float = 0.0, ry: float = 0.0, rz: float = 0.0,
) -> Any:
    """Rotate *entity* by Euler delta radians. Returns *entity*."""
    rotate_by = getattr(entity, "rotate_by", None)
    if callable(rotate_by):
        return rotate_by(rx, ry, rz)
    prev = getattr(entity, "rotation", (0.0, 0.0, 0.0))
    entity.rotation = (
        float(prev[0] + rx), float(prev[1] + ry), float(prev[2] + rz),
    )
    return entity


def scale(entity: Any, factor: float = 1.0) -> Any:
    """Multiply *entity*'s scale by *factor* uniformly. Returns *entity*."""
    prev = getattr(entity, "scale", (1.0, 1.0, 1.0))
    entity.scale = (
        float(prev[0] * factor),
        float(prev[1] * factor),
        float(prev[2] * factor),
    )
    return entity


# ---------------------------------------------------------------------------
# Lifecycle + scene IO
# ---------------------------------------------------------------------------


def delete(entity: Any, *, app: "App | None" = None) -> None:
    """Remove *entity* from its owning app. Idempotent + None-safe.

    Prefers :meth:`ModelHandle.destroy` when available; falls back to
    list removal for lights + cameras (which don't currently expose a
    destroy method).
    """
    if entity is None:
        return
    destroy = getattr(entity, "destroy", None)
    if callable(destroy):
        destroy()
        return
    a = _resolve_app(app)
    for coll in (a.models, a.lights, a.cameras):
        try:
            coll.remove(entity)
        except ValueError:
            continue
    a.trace.append(("delete", getattr(entity, "id", -1)))


def clear_scene(*, app: "App | None" = None) -> None:
    """Remove every model, light, and camera from *app*.

    Loops via :func:`delete` so each removal is trace-logged. Also clears
    :attr:`App.active_camera` so a subsequent :func:`set_camera` call
    rebinds cleanly.
    """
    a = _resolve_app(app)
    for e in list(a.models):
        delete(e, app=a)
    for e in list(a.lights):
        delete(e, app=a)
    for e in list(a.cameras):
        delete(e, app=a)
    a.active_camera = None
    a.trace.append(("clear_scene",))


def save_scene(path: str | Path, *, app: "App | None" = None) -> Path:
    """Persist the current scene state to *path* as a plain YAML snapshot.

    A lightweight round-trip format tailored for the REPL: dumps every
    model / light / camera as a dict with ``kind``, ``id``, ``position``,
    ``rotation``, ``scale``, ``color``, and ``intensity`` fields. Full
    :class:`Scene` serialisation lives on :meth:`Scene.save` and is not
    used here because :class:`App` is scene-agnostic.
    """
    import yaml

    a = _resolve_app(app)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    snapshot: dict[str, Any] = {
        "models": [
            {
                "id": m.id,
                "path": m.path,
                "position": list(m.position),
                "rotation": list(m.rotation),
                "scale": list(m.scale),
                "visible": m.visible,
            }
            for m in a.models
        ],
        "lights": [
            {
                "id": lt.id,
                "position": list(lt.position),
                "color": list(lt.color),
                "intensity": lt.intensity,
            }
            for lt in a.lights
        ],
        "cameras": [
            {
                "id": c.id,
                "position": list(c.position),
                "look_at": list(c.look_at),
                "fov_deg": c.fov_deg,
            }
            for c in a.cameras
        ],
    }
    p.write_text(yaml.safe_dump(snapshot, sort_keys=False), encoding="utf-8")
    a.trace.append(("save_scene", str(p)))
    return p


def load_scene(path: str | Path, *, app: "App | None" = None) -> None:
    """Replace the current scene with the YAML snapshot at *path*.

    Round-trips the format produced by :func:`save_scene`. Calls
    :func:`clear_scene` first so the load is a straight replacement.
    """
    import yaml

    a = _resolve_app(app)
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    clear_scene(app=a)
    for m in raw.get("models") or []:
        handle = a.load_model(m.get("path", "primitive:cube"))
        handle.position = tuple(m.get("position", (0.0, 0.0, 0.0)))
        handle.rotation = tuple(m.get("rotation", (0.0, 0.0, 0.0)))
        handle.scale = tuple(m.get("scale", (1.0, 1.0, 1.0)))
        handle.visible = bool(m.get("visible", True))
    for lt in raw.get("lights") or []:
        a.spawn_light(
            position=tuple(lt.get("position", (0.0, 0.0, 0.0))),
            color=tuple(lt.get("color", (1.0, 1.0, 1.0))),
            intensity=float(lt.get("intensity", 1.0)),
        )
    for c in raw.get("cameras") or []:
        a.spawn_camera(
            position=tuple(c.get("position", (0.0, 0.0, 5.0))),
            look_at=tuple(c.get("look_at", (0.0, 0.0, 0.0))),
        )
    a.trace.append(("load_scene", str(p)))


def set_background(
    color: tuple[float, float, float, float] | tuple[float, float, float],
    *,
    app: "App | None" = None,
) -> None:
    """Set the renderer clear colour on *app*'s config.

    Accepts either an RGB or RGBA tuple; RGB gets an implicit ``alpha=1``.
    Stored on :attr:`AppConfig.clear_color` so the next frame picks it up.
    """
    a = _resolve_app(app)
    if len(color) == 3:
        rgba = (float(color[0]), float(color[1]), float(color[2]), 1.0)
    else:
        rgba = tuple(float(c) for c in color[:4])  # type: ignore[assignment]
    a.config.clear_color = rgba
    a.trace.append(("set_background", rgba))


# ---------------------------------------------------------------------------
# Capture helpers
# ---------------------------------------------------------------------------


def screenshot(path: str | Path, *, app: "App | None" = None) -> Path:
    """One-shot screenshot — delegates to :meth:`App.take_screenshot`.

    Returns the resolved :class:`Path`. When the underlying capture action
    can't render (headless with no wgpu), the returned path may not exist
    on disk — the trace still records the intent.
    """
    a = _resolve_app(app)
    result = a.take_screenshot(str(path))
    return Path(result.get("path", str(path)))


def record_gif(
    path: str | Path, frames: int = 60, *, app: "App | None" = None,
) -> Path:
    """Record *frames* frames into an MP4 (GIF-shaped) file at *path*.

    Thin wrapper around :meth:`App.start_recording` /
    :meth:`App.stop_recording`. Runs *frames* frames with the app's
    current tick loop via :meth:`App.render_frame` so the caller doesn't
    need to spin up their own loop.
    """
    a = _resolve_app(app)
    a.start_recording(path=str(path))
    try:
        for _ in range(int(frames)):
            a.render_frame()
    finally:
        a.stop_recording()
    return Path(path)


# ---------------------------------------------------------------------------
# Editor panel focus
# ---------------------------------------------------------------------------


def open_material_graph(*, shell: Any = None) -> Any:
    """Focus the Material Graph visual canvas in the editor shell.

    Returns the :class:`MaterialGraphCanvas` instance so the caller can
    interact with it directly from the REPL (e.g. ``mg = open_material_graph()``
    then ``mg.place_node("ConstColor", 40, 40)``).

    When no shell reference is given, tries to resolve one from the
    running :class:`App`'s ``editor_shell`` attribute; falls back to
    :attr:`EditorShell._implicit` when available.
    """
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
    )
    resolved = shell
    if resolved is None:
        try:
            from pharos_engine.app import App as _App
            app = _App._get_implicit()
            resolved = getattr(app, "editor_shell", None)
        except Exception:
            resolved = None
    if resolved is None:
        try:
            from pharos_editor.ui.editor.shell import EditorShell
            resolved = getattr(EditorShell, "_implicit", None)
        except Exception:
            resolved = None
    canvas = getattr(resolved, "_material_graph_canvas", None) if resolved else None
    if canvas is None:
        # No live shell — spin up a bare canvas so the REPL still has a
        # target to bind. Callers that were expecting an editor tab
        # will notice the returned instance isn't docked.
        canvas = MaterialGraphCanvas()
    # Best-effort focus: show the window / raise the tab. All DPG calls
    # are guarded so a headless REPL still gets the canvas back.
    try:
        import dearpygui.dearpygui as dpg
        wrapper = None
        try:
            wrapper = resolved._panel_windows.get("material_graph_canvas")  # type: ignore[union-attr]
        except Exception:
            wrapper = None
        if wrapper is not None:
            try:
                wrapper.show()
                dpg.focus_item(wrapper._window_tag)  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass
    return canvas


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def help() -> str:  # noqa: A001 — deliberate shadow, REPL-scoped name
    """Return a Markdown cheat sheet of every helper in this module.

    Introspects the module's public functions and pulls the first line of
    each docstring. Used by the REPL panel's ``/help`` command so newly
    added helpers surface automatically.
    """
    import inspect
    import sys

    mod = sys.modules[__name__]
    lines = ["# SlapPyEngine editor helpers", ""]
    for name in __all__:
        obj = getattr(mod, name, None)
        if obj is None or obj is help or not callable(obj):
            continue
        doc = inspect.getdoc(obj) or ""
        first = doc.splitlines()[0] if doc else ""
        try:
            sig = str(inspect.signature(obj))
        except (TypeError, ValueError):
            sig = "(...)"
        lines.append(f"- `{name}{sig}` — {first}")
    return "\n".join(lines) + "\n"


__all__ = [
    "spawn_cube",
    "spawn_sphere",
    "spawn_plane",
    "spawn_light",
    "set_camera",
    "load_model",
    "load_texture",
    "load_shader",
    "reload_shader",
    "list_entities",
    "select",
    "move",
    "rotate",
    "scale",
    "delete",
    "clear_scene",
    "save_scene",
    "load_scene",
    "set_background",
    "screenshot",
    "record_gif",
    "open_material_graph",
    "help",
    "ShaderHandle",
]
