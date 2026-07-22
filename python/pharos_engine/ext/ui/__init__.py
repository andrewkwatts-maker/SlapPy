"""Legacy shim: ``pharos_engine.ext.ui`` moved to ``pharos_editor.ui``.

The pharos-engine wheel intentionally does not include the editor UI
(saves the ~15MB DearPyGui footprint on headless/server deployments).
Install ``pharos-editor`` and import from ``pharos_editor.ui`` instead.
"""
from __future__ import annotations


def __getattr__(name: str):  # pragma: no cover - error path
    raise ImportError(
        f"pharos_engine.ext.ui.{name} is no longer bundled with pharos-engine. "
        "Install pharos-editor (pip install pharos-editor) and import from "
        f"pharos_editor.ui.{name}."
    )


__all__: list[str] = []
