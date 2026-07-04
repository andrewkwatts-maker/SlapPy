"""Layout I/O actions — save / load layout snapshots to caller-chosen files.

Backs two :class:`~slappyengine.tool_router.ToolAction` rows added by the
BB1 STUB-triage sprint tick:

* ``file.save_layout_as`` — snapshot the current shell layout and write
  it to a caller-supplied YAML path (or prompted-for path).
* ``file.load_layout_from_file`` — read a layout YAML from disk and
  apply it to the shell.

These are the *explicit-path* counterparts to
:class:`slappyengine.ui.editor.layout_persistence.LayoutPersistence`,
which owns the *implicit* per-project ``.slappy/layout.yaml`` path.
Users invoke these when they want to share a layout across projects
(export from Project A, import into Project B) or when they want to
keep a named preset library (``combat.layout.yaml``, ``authoring.layout.yaml``)
outside the project tree.

Design goals
------------

* **YAML round-trippable** — the same schema
  :class:`LayoutPersistence` writes.
* **Atomic write** — temp file + ``os.replace`` so a crash mid-write
  never leaves a partial layout behind.
* **Headless-safe** — the tests pass a ``layout=`` override + explicit
  ``path=`` so no shell needs to exist.

Return contract for ``save_layout_as``
--------------------------------------

* ``{"status": "saved", "path": str, "size_bytes": int}`` on success.
* ``{"status": "no_path"}`` when no path override was supplied and no
  shell prompt hook is reachable.
* ``{"status": "no_layout"}`` when no shell was reachable and no
  ``ctx["layout"]`` override was supplied.
* ``{"status": "error", "message": str}`` when the write raised.

Return contract for ``load_layout_from_file``
---------------------------------------------

* ``{"status": "loaded", "path": str, "applied": bool,
  "theme": "<name>", "panel_count": int}`` on success.
* ``{"status": "no_path"}`` when no path was resolved.
* ``{"status": "missing", "path": str}`` when the file doesn't exist.
* ``{"status": "malformed", "path": str}`` when the YAML fails schema.
* ``{"status": "error", "message": str}`` when reading raised.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _resolve_save_path(ctx: dict[str, Any]) -> Path | None:
    """Return the destination Path for a save-layout-as flow.

    Search order:

    1. ``ctx["path"]`` — direct override.
    2. ``ctx["shell"].prompt_save_path(default_name)`` — the same shell
       hook that ``theme.export_current`` uses. Passes a ``.layout.yaml``
       default filename so the Tk chooser suggests the right extension.
    """
    override = ctx.get("path")
    if override is not None:
        return Path(override)
    shell = ctx.get("shell")
    if shell is None:
        return None
    prompter = getattr(shell, "prompt_save_path", None)
    if not callable(prompter):
        return None
    try:
        picked = prompter("layout.layout.yaml")
    except Exception:  # noqa: BLE001
        return None
    if not picked:
        return None
    return Path(picked)


def _resolve_load_path(ctx: dict[str, Any]) -> Path | None:
    """Return the source Path for a load-layout-from-file flow.

    Mirror of :func:`_resolve_save_path` — reads
    ``ctx["shell"].prompt_open_path`` instead of ``prompt_save_path``.
    """
    override = ctx.get("path")
    if override is not None:
        return Path(override)
    shell = ctx.get("shell")
    if shell is None:
        return None
    prompter = getattr(shell, "prompt_open_path", None)
    if not callable(prompter):
        return None
    try:
        picked = prompter(".layout.yaml")
    except Exception:  # noqa: BLE001
        return None
    if not picked:
        return None
    return Path(picked)


# ---------------------------------------------------------------------------
# Snapshot resolution
# ---------------------------------------------------------------------------


def _resolve_layout(ctx: dict[str, Any]) -> Any:
    """Return the :class:`EditorLayout` to save.

    Search order:

    1. ``ctx["layout"]`` — direct override (tests pass this).
    2. ``LayoutPersistence().snapshot_from_shell(ctx["shell"])`` — snap
       the live shell state.
    """
    override = ctx.get("layout")
    if override is not None:
        return override
    shell = ctx.get("shell")
    if shell is None:
        return None
    try:
        from slappyengine.ui.editor.layout_persistence import (
            LayoutPersistence,
        )
    except Exception:  # noqa: BLE001
        return None
    try:
        persistence = LayoutPersistence()
        return persistence.snapshot_from_shell(shell)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def _atomic_write_text(target: Path, text: str) -> None:
    """Write *text* to *target* via temp + ``os.replace``.

    Same pattern LayoutPersistence.save + UserThemeStore._atomic_write_text
    use — kept in this module so the layout-I/O actions have no import
    cycle back into the persistence layer.
    """
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
                pass
        os.replace(tmp_path, target)
    except Exception:
        # Best-effort cleanup on failure.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Public actions
# ---------------------------------------------------------------------------


def save_layout_as(ctx: dict[str, Any]) -> dict[str, Any]:
    """Snapshot the current layout and write it to a caller-chosen path.

    See the module docstring for the return contract.
    """
    layout = _resolve_layout(ctx)
    if layout is None:
        return {"status": "no_layout"}
    path = _resolve_save_path(ctx)
    if path is None:
        return {"status": "no_path"}

    try:
        import yaml
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"yaml missing: {exc}"}

    try:
        payload = yaml.safe_dump(
            layout.to_dict(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    try:
        _atomic_write_text(path, payload)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    return {
        "status": "saved",
        "path": str(path),
        "size_bytes": len(payload.encode("utf-8")),
    }


def load_layout_from_file(ctx: dict[str, Any]) -> dict[str, Any]:
    """Read a layout YAML file and apply it to the shell.

    Parameters (via ``ctx``)
    ------------------------
    * ``path`` — the source file. When absent the shell's
      ``prompt_open_path`` hook is invoked.
    * ``apply`` — when truthy (default: ``True``), the loaded layout is
      pushed onto the shell via ``LayoutPersistence.apply_to_shell``.
      Set to ``False`` to just parse + return the layout without
      mutating the shell (useful for previews).
    * ``shell`` — the shell to apply to. When ``None`` the ``applied``
      flag comes back ``False`` but the load still succeeds.

    Returns
    -------
    dict
        See the module docstring for the full contract.
    """
    path = _resolve_load_path(ctx)
    if path is None:
        return {"status": "no_path"}
    if not path.is_file():
        return {"status": "missing", "path": str(path)}

    try:
        import yaml
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": f"yaml missing: {exc}"}

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"status": "error", "message": str(exc)}

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return {"status": "malformed", "path": str(path), "reason": str(exc)}

    if not isinstance(data, dict):
        return {"status": "malformed", "path": str(path)}

    try:
        from slappyengine.ui.editor.layout_persistence import (
            EditorLayout,
            LayoutPersistence,
            SCHEMA_VERSION,
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}

    if int(data.get("schema_version", 0)) != SCHEMA_VERSION:
        return {"status": "malformed", "path": str(path)}

    try:
        layout = EditorLayout.from_dict(data)
    except (TypeError, ValueError, KeyError) as exc:
        return {"status": "malformed", "path": str(path), "reason": str(exc)}

    applied = False
    should_apply = bool(ctx.get("apply", True))
    shell = ctx.get("shell")
    if should_apply and shell is not None:
        try:
            persistence = LayoutPersistence()
            persistence.apply_to_shell(shell, layout)
            applied = True
        except Exception:  # noqa: BLE001
            applied = False

    return {
        "status": "loaded",
        "path": str(path),
        "applied": applied,
        "theme": layout.theme,
        "panel_count": len(layout.panels),
    }


__all__ = [
    "save_layout_as",
    "load_layout_from_file",
]
