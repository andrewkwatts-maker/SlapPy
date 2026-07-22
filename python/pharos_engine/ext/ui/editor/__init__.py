"""Legacy shim: ``pharos_engine.ext.ui.editor`` moved to ``pharos_editor.ui.editor``.

Install ``pharos-editor`` and import from ``pharos_editor.ui.editor``.
"""
from __future__ import annotations


def __getattr__(name: str):  # pragma: no cover - error path
    raise ImportError(
        f"pharos_engine.ext.ui.editor.{name} is no longer bundled with pharos-engine. "
        "Install pharos-editor (pip install pharos-editor) and import from "
        f"pharos_editor.ui.editor.{name}."
    )


__all__: list[str] = []
