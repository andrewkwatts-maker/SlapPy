"""Bridge between the Notebook Diary panel and a softbody world.

This shim exists to close the biggest remaining STUB in the engine
feature map (rows 80 + 223, ``docs/engine_feature_map_2026_07_04.md``):
the diary tick's ``from slappyengine.softbody import step`` fails on a
fresh checkout because ``python/slappyengine/softbody/`` is
uncommitted WIP. The bridge picks the best available softbody-world
constructor at call time and gives the diary a stable file-import
entry point.

Two public functions:

* :func:`resolve_softbody_class` — return the constructor the diary
  should use to build a world. Prefers the WIP
  ``slappyengine.softbody.SoftBodyWorld`` when it is importable so a
  wheel-shipped or dev-checkout engine keeps working; falls back to
  the always-tracked ``slappyengine.dynamics.SoftBodyWorld``. Raises
  a friendly :class:`ImportError` naming both attempted paths when
  both are missing.

* :func:`import_softbody_file` — read a ``.softbody.yaml`` or
  ``.softbody.json`` file and register the described body into
  ``world``. Returns the registered
  :class:`slappyengine.dynamics.Body` (or the softbody-native body
  duck it registered on the alternative path).

The bridge deliberately does **not** patch
``notebook_diary_page.py`` — that file is pinned read-only in the
current sprint window (see the sprint plan). The diary panel can
opt into this bridge in a subsequent sprint by rewiring the two
call sites (line 539 for ``studio.softbody_stage()`` and line 610
for the per-tick ``softbody.step``).

See ``docs/diary_softbody_bridge_2026_07_04.md`` for the full
investigation write-up.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Union

_LOG = logging.getLogger(__name__)


# Accepted file suffixes for :func:`import_softbody_file`. Both the
# double-suffix (``.softbody.json``) and the single-suffix (``.json``)
# forms are recognised so users can point the panel at either a raw
# dynamics-serialised body or a hand-authored fixture.
_JSON_SUFFIXES = (".softbody.json", ".json")
_YAML_SUFFIXES = (".softbody.yaml", ".softbody.yml", ".yaml", ".yml")

# Friendly message when both softbody roots are unavailable. Kept as a
# module-level constant so tests can pin on a stable substring.
_MISSING_MESSAGE = (
    "diary_softbody_bridge.resolve_softbody_class: neither "
    "'slappyengine.softbody.SoftBodyWorld' (WIP) nor "
    "'slappyengine.dynamics.SoftBodyWorld' (tracked fallback) could "
    "be imported. Install the engine wheel or run from a checkout "
    "that includes 'python/slappyengine/dynamics/'."
)


PathLike = Union[str, Path]


def resolve_softbody_class() -> Callable[..., Any]:
    """Return the softbody-world constructor the diary should use.

    Import order:

    1. ``slappyengine.softbody.SoftBodyWorld`` — the WIP lattice-based
       softbody world. Preferred so that a wheel-installed engine or a
       dev checkout that has committed the softbody tree keeps behaving
       exactly as before.
    2. ``slappyengine.dynamics.SoftBodyWorld`` — the always-tracked
       XPBD substrate (alias for :class:`slappyengine.dynamics.World`).
       Provides the same ``.step(dt)`` surface the diary tick needs.

    Raises
    ------
    ImportError
        When both paths fail. The message names both attempted paths so
        the user knows exactly which install step is missing.
    """
    # First-choice path — the WIP softbody surface.
    try:
        from slappyengine.softbody import SoftBodyWorld as _WipWorld  # type: ignore[import-not-found]
        return _WipWorld  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001 - any import failure means "fall back"
        _LOG.debug(
            "resolve_softbody_class: slappyengine.softbody unavailable (%s: %s); "
            "falling back to slappyengine.dynamics.",
            type(exc).__name__, exc,
        )

    # Fallback — the always-tracked dynamics substrate.
    try:
        from slappyengine.dynamics import SoftBodyWorld as _DynWorld
        return _DynWorld  # type: ignore[return-value]
    except Exception as exc:  # noqa: BLE001
        _LOG.debug(
            "resolve_softbody_class: slappyengine.dynamics fallback also "
            "failed (%s: %s); raising friendly ImportError.",
            type(exc).__name__, exc,
        )

    raise ImportError(_MISSING_MESSAGE)


def _load_json_payload(path: Path) -> dict[str, Any]:
    """Decode a JSON file into a dict, with a stable error surface."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"import_softbody_file: {path} is not valid JSON "
            f"({exc.msg} at line {exc.lineno} col {exc.colno})"
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"import_softbody_file: {path} must decode to a dict; "
            f"got {type(raw).__name__}"
        )
    return raw


def _load_yaml_payload(path: Path) -> dict[str, Any]:
    """Decode a YAML file into a dict.

    Uses ``yaml.safe_load`` when PyYAML is available, otherwise falls
    back to a naive ``key: value`` line parser (numeric coercion +
    inline JSON support for lists / dicts). Callers only need
    top-level ``kind`` / ``node_offset`` / ``node_count`` / ``label``
    / ``parameters`` keys to survive the fallback path — good enough
    for the diary's small hand-authored fixtures.
    """
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]

        raw = yaml.safe_load(text)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(
                f"import_softbody_file: {path} must decode to a dict; "
                f"got {type(raw).__name__}"
            )
        return raw
    except ImportError:
        # PyYAML unavailable — naive parser: "key: value" lines only.
        # Supports ints, floats, quoted strings, and inline JSON on the
        # right-hand side for list / dict values.
        out: dict[str, Any] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            k, _, v = stripped.partition(":")
            key = k.strip()
            val = v.strip()
            # Try JSON first — catches lists, dicts, quoted strings, numbers.
            try:
                out[key] = json.loads(val)
                continue
            except json.JSONDecodeError:
                pass
            # Then plain numeric coercion.
            try:
                if "." in val or "e" in val or "E" in val:
                    out[key] = float(val)
                else:
                    out[key] = int(val)
                continue
            except ValueError:
                pass
            # Fall back to raw string (strip surrounding quotes if any).
            out[key] = val.strip('"').strip("'")
        return out


def _decode_body_via_dynamics(payload: dict[str, Any]) -> Any:
    """Try the tracked ``dynamics.body_from_dict`` decoder first.

    Returns the decoded :class:`slappyengine.dynamics.Body` or ``None``
    when the tracked path is unavailable (dynamics missing).
    """
    try:
        from slappyengine.dynamics import Body, body_from_dict
    except Exception:  # noqa: BLE001
        return None
    try:
        return body_from_dict(payload)
    except Exception as exc:  # noqa: BLE001
        # The dynamics decoder is strict; on the naive-YAML path we may
        # have a payload that lacks its ``_kind`` marker or ``material``
        # sub-dict. Build a minimal Body directly so hand-authored
        # fixtures keep working.
        _LOG.debug(
            "_decode_body_via_dynamics: body_from_dict raised %s: %s; "
            "building minimal Body from payload keys.",
            type(exc).__name__, exc,
        )
        return Body(
            kind=str(payload.get("kind", "lattice")),
            parameters=dict(payload.get("parameters", {})),
            node_offset=int(payload.get("node_offset", 0)),
            node_count=int(payload.get("node_count", 0)),
            label=str(payload.get("label", "")),
        )


def _register_body(world: Any, body: Any) -> Any:
    """Attach ``body`` to ``world`` using whichever surface is present.

    Dispatch order:

    1. ``world.register_body(body)`` — the tracked dynamics API. Preferred
       because it validates the body slice against the world's node
       array.
    2. ``world.bodies.append(body)`` — the softbody duck-type fallback
       (also matches ``dynamics.World.bodies`` list layout, so this
       branch is safe when ``register_body`` is missing entirely).

    Returns ``body`` in either case so callers can chain.
    """
    register = getattr(world, "register_body", None)
    if callable(register):
        try:
            register(body)
            return body
        except Exception as exc:  # noqa: BLE001
            _LOG.debug(
                "_register_body: world.register_body raised %s: %s; "
                "falling back to bodies.append.",
                type(exc).__name__, exc,
            )
    bodies = getattr(world, "bodies", None)
    if bodies is not None and hasattr(bodies, "append"):
        bodies.append(body)
        return body
    raise TypeError(
        "import_softbody_file: world must expose either "
        "register_body(body) or a bodies.append(body) surface; got "
        f"{type(world).__name__}"
    )


def import_softbody_file(path: PathLike, world: Any) -> Any:
    """Import a ``.softbody.yaml`` / ``.softbody.json`` file into
    ``world``.

    Parameters
    ----------
    path:
        Filesystem path to a softbody description. Suffix determines
        the decoder: ``.json``/``.softbody.json`` uses :mod:`json`;
        ``.yaml``/``.yml``/``.softbody.yaml``/``.softbody.yml`` uses
        PyYAML when available with a naive parser fallback.
    world:
        Target world — either a tracked
        :class:`slappyengine.dynamics.World` or a WIP
        ``slappyengine.softbody.SoftBodyWorld`` duck. The bridge
        prefers ``world.register_body`` when present.

    Returns
    -------
    Any
        The registered body — a :class:`slappyengine.dynamics.Body`
        on the tracked path, or whatever type the WIP softbody
        surface returned.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If the suffix is unsupported, or the file contents fail to
        decode into a top-level dict.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"import_softbody_file: {p} does not exist"
        )
    suffix_lower = p.name.lower()
    if any(suffix_lower.endswith(s) for s in _JSON_SUFFIXES):
        payload = _load_json_payload(p)
    elif any(suffix_lower.endswith(s) for s in _YAML_SUFFIXES):
        payload = _load_yaml_payload(p)
    else:
        raise ValueError(
            f"import_softbody_file: unsupported suffix on {p!r}; "
            f"expected one of {_JSON_SUFFIXES + _YAML_SUFFIXES}"
        )

    body = _decode_body_via_dynamics(payload)
    if body is None:
        # Dynamics missing entirely — build a bare namespace-like body
        # that satisfies ``world.bodies.append``. This branch should
        # only fire in extremely stripped-down installs.
        class _MinimalBody:
            def __init__(self, d: dict[str, Any]) -> None:
                self.kind = str(d.get("kind", "lattice"))
                self.parameters = dict(d.get("parameters", {}))
                self.node_offset = int(d.get("node_offset", 0))
                self.node_count = int(d.get("node_count", 0))
                self.label = str(d.get("label", ""))
        body = _MinimalBody(payload)

    return _register_body(world, body)


__all__ = [
    "import_softbody_file",
    "resolve_softbody_class",
]
